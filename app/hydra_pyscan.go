package main

// A reader of Python's structure, for the sub-agent contract's validator and joiner
// (hydra_piece.go, hydra_assemble.go). Those were measured with Python's ast module and
// the app has no Python to ask, so this reads a script into the same tree: the same
// statements on the same lines, nested the same way, and walked in the same order,
// because the joiner cuts scripts up by those lines and the checks report what they
// find in that order. That takes every expression's shape, not just the statements'.
//
// It reads, and doesn't judge. It looks nothing up, checks nothing the compiler checks,
// and a syntax error it doesn't see does no harm: the result check runs the script in
// real Blender anyway. The other way round would do harm, because a piece that Python
// accepts must never be rejected here. So the tokens follow CPython's tokenizer, the
// grammar is as wide as Python's, and what only says what's wrong happens in a second
// pass, once the first has already failed, as in CPython's parser. That's also where
// most of the words of its errors come from, kept because they end up in a fallback's
// reasons. worker-model/tools/check_join_parity.py compares all this with ast, on the
// standard library, on every reply we have and on damaged code.

import (
	"fmt"
	"strings"
	"unicode"
	"unicode/utf8"
)

// pySyntaxError is what Python's SyntaxError would say. Line 0 means it has none.
type pySyntaxError struct {
	line int
	msg  string
}

// ---------- tokens ----------

type pyTokenKind int

const (
	pyTokEnd pyTokenKind = iota
	pyTokName
	pyTokNumber
	pyTokString
	pyTokOp
	pyTokNewline
	pyTokIndent
	pyTokDedent
	pyTokFStart
	pyTokFMiddle
	pyTokFEnd
	pyTokStop // the tokenizer stopped here, and err says why
)

type pyToken struct {
	kind      pyTokenKind
	text      string
	line, end int
	at        int // where it starts in the source
	level     int // open brackets once it's read
	err       *pySyntaxError
}

const (
	pyTabSize       = 8
	pyMaxIndent     = 100
	pyMaxLevel      = 200
	pyMaxFStrings   = 150
	pyMaxFieldDepth = 150
	pyEOF           = -1
)

type pyBracket struct {
	c    byte
	line int
}

// pyFMode is one f-string being read. inString is off inside a {replacement field}.
type pyFMode struct {
	quote      byte
	quoteSize  int
	raw        bool
	line       int
	depth      int // open brackets inside this f-string
	fieldDepth int // the bracket depth its current field began at, -1 outside one
	inSpec     bool
	inString   bool
}

// pyLexer is CPython's tokenizer (Parser/lexer/lexer.c), reduced to what the reader
// uses. hard is an error Python reports wherever the parser had got to; the others
// count only if the parser gets that far.
type pyLexer struct {
	src      string
	cur      int
	line     int
	toks     []pyToken
	bol      bool
	indents  []int
	alts     []int
	pending  int
	open     []pyBracket
	modes    []*pyFMode
	hard     *pySyntaxError
	unclosed *pySyntaxError
}

// pyNormalize does what compile() does to source text first.
func pyNormalize(src string) string {
	src = strings.ReplaceAll(src, "\r\n", "\n")
	src = strings.ReplaceAll(src, "\r", "\n")
	if src != "" && !strings.HasSuffix(src, "\n") {
		src += "\n"
	}
	return src
}

func pyLex(src string) *pyLexer {
	l := &pyLexer{src: src, line: 1, bol: true, indents: []int{0}, alts: []int{0}}
	for l.next() {
	}
	return l
}

func (l *pyLexer) peek() int {
	if l.cur >= len(l.src) {
		return pyEOF
	}
	return int(l.src[l.cur])
}

func (l *pyLexer) peekAt(n int) int {
	if l.cur+n >= len(l.src) {
		return pyEOF
	}
	return int(l.src[l.cur+n])
}

func (l *pyLexer) read() int {
	c := l.peek()
	if c != pyEOF {
		l.cur++
		if c == '\n' {
			l.line++
		}
	}
	return c
}

// eofLine is the line Python gives the end of the source: its last line, while l.line
// has gone past that line's newline.
func (l *pyLexer) eofLine() int {
	if l.line > 1 {
		return l.line - 1
	}
	return 1
}

func (l *pyLexer) emit(kind pyTokenKind, start, line int) bool {
	l.toks = append(l.toks, pyToken{kind: kind, text: l.src[start:l.cur], line: line, end: l.line, at: start, level: len(l.open)})
	return true
}

// stop ends the tokens with an error the parser meets if it gets here. If a bracket is
// open by then, that may be what Python reports instead.
func (l *pyLexer) stop(line int, format string, args ...any) bool {
	e := &pySyntaxError{line, fmt.Sprintf(format, args...)}
	l.toks = append(l.toks, pyToken{kind: pyTokStop, line: line, end: line, level: len(l.open), err: e})
	if len(l.open) > 0 {
		b := l.open[len(l.open)-1]
		l.unclosed = &pySyntaxError{b.line, fmt.Sprintf("'%c' was never closed", b.c)}
	}
	return false
}

// fail is a stop Python reports however far the parser got.
func (l *pyLexer) fail(line int, format string, args ...any) bool {
	l.stop(line, format, args...)
	l.hard = l.toks[len(l.toks)-1].err
	return false
}

func (l *pyLexer) mode() *pyFMode {
	if len(l.modes) == 0 {
		return nil
	}
	return l.modes[len(l.modes)-1]
}

func (l *pyLexer) next() bool {
	if m := l.mode(); m != nil && m.inString {
		return l.fstringPart(m)
	}
	return l.regular()
}

// indentation reads a line's leading space, and works out its indents and dedents.
func (l *pyLexer) indentation() (blank, ok bool) {
	col, alt, contCol := 0, 0, 0
read:
	for {
		switch l.peek() {
		case ' ':
			col, alt = col+1, alt+1
			l.cur++
		case '\t':
			col, alt = (col/pyTabSize+1)*pyTabSize, alt+1
			l.cur++
		case '\f':
			col, alt = 0, 0
			l.cur++
		case '\\':
			// A backslash can't split indentation over lines: the first one sets it.
			if contCol == 0 {
				contCol = col
			}
			l.cur++
			if !l.continuation() {
				return false, false
			}
		default:
			break read
		}
	}
	if c := l.peek(); c == '#' || c == '\n' {
		return true, true
	}
	if len(l.open) > 0 {
		return false, true
	}
	if contCol != 0 {
		col, alt = contCol, contCol
	}
	top := len(l.indents) - 1
	switch {
	case col == l.indents[top]:
		if alt != l.alts[top] {
			return false, l.tabError()
		}
	case col > l.indents[top]:
		if len(l.indents) >= pyMaxIndent {
			return false, l.stop(l.line, "too many levels of indentation")
		}
		if alt <= l.alts[top] {
			return false, l.tabError()
		}
		l.pending++
		l.indents, l.alts = append(l.indents, col), append(l.alts, alt)
	default:
		for top > 0 && col < l.indents[top] {
			l.pending--
			top--
		}
		l.indents, l.alts = l.indents[:top+1], l.alts[:top+1]
		if col != l.indents[top] {
			return false, l.stop(l.line, "unindent does not match any outer indentation level")
		}
		if alt != l.alts[top] {
			return false, l.tabError()
		}
	}
	return false, true
}

func (l *pyLexer) tabError() bool {
	return l.stop(l.line, "inconsistent use of tabs and spaces in indentation")
}

// continuation has read a backslash: only a newline, and then more source, can follow.
func (l *pyLexer) continuation() bool {
	if l.peek() != '\n' {
		return l.stop(l.line, "unexpected character after line continuation character")
	}
	line := l.line
	l.read()
	if l.peek() == pyEOF {
		if len(l.open) > 0 {
			return l.stopAtOpen()
		}
		return l.stop(line, "unexpected EOF while parsing")
	}
	return true
}

func (l *pyLexer) stopAtOpen() bool {
	b := l.open[len(l.open)-1]
	return l.stop(b.line, "'%c' was never closed", b.c)
}

func (l *pyLexer) regular() bool {
	for {
		blank := false
		if l.bol {
			l.bol = false
			var ok bool
			if blank, ok = l.indentation(); !ok {
				return false
			}
		}
		for ; l.pending != 0; l.pending -= pySign(l.pending) {
			kind, line := pyTokIndent, l.line
			if l.pending < 0 {
				kind = pyTokDedent
				if l.peek() == pyEOF {
					line = l.eofLine()
				}
			}
			l.toks = append(l.toks, pyToken{kind: kind, line: line, end: line, level: len(l.open)})
		}
		for {
			c := l.peek()
			if c != ' ' && c != '\t' && c != '\f' {
				break
			}
			l.cur++
		}
		if l.peek() == '#' {
			for c := l.peek(); c != pyEOF && c != '\n'; c = l.peek() {
				l.cur++
			}
		}
		start, line := l.cur, l.line
		c := l.peek()
		switch {
		case c == pyEOF:
			if len(l.open) > 0 {
				return l.stopAtOpen()
			}
			l.toks = append(l.toks, pyToken{kind: pyTokEnd, line: l.eofLine(), end: l.eofLine()})
			return false
		case c == '\n':
			l.read()
			l.bol = true
			if blank || len(l.open) > 0 {
				continue
			}
			return l.emit(pyTokNewline, start, line)
		case pyIdentByte(c) && !pyDigit(c):
			return l.word(start)
		case c == '.' && pyDigit(l.peekAt(1)):
			l.cur++
			return l.fraction(start)
		case pyDigit(c):
			return l.number(start)
		case c == '"' || c == '\'':
			return l.stringToken(start)
		case c == '\\':
			l.cur++
			if !l.continuation() {
				return false
			}
			l.bol = false
			continue
		}
		return l.punctuation(start)
	}
}

func pySign(n int) int {
	if n < 0 {
		return -1
	}
	return 1
}

func pyDigit(c int) bool { return c >= '0' && c <= '9' }

func pyHexDigit(c int) bool {
	return pyDigit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')
}

// pyIdentByte is a byte that can be in a name. Anything past ASCII can, for now: word
// looks at those properly.
func pyIdentByte(c int) bool {
	return c == '_' || pyDigit(c) || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c >= 128
}

// word reads a name, or the prefix of a string.
func (l *pyLexer) word(start int) bool {
	var b, r, u, f bool
	for {
		c := l.peek()
		switch {
		case !(b || u || f) && (c == 'b' || c == 'B'):
			b = true
		case !(b || u || r || f) && (c == 'u' || c == 'U'):
			u = true
		case !(r || u) && (c == 'r' || c == 'R'):
			r = true
		case !(f || b || u) && (c == 'f' || c == 'F'):
			f = true
		default:
			return l.name(start)
		}
		l.cur++
		if c := l.peek(); c == '"' || c == '\'' {
			if f {
				return l.fstringStart(start, r)
			}
			return l.stringToken(start)
		}
	}
}

func (l *pyLexer) name(start int) bool {
	ascii := true
	for pyIdentByte(l.peek()) {
		if l.peek() >= 128 {
			ascii = false
		}
		l.cur++
	}
	if !ascii {
		for i, r := range l.src[start:l.cur] {
			if (i == 0 && !pyIDStart(r)) || !pyIDContinue(r) {
				if pyPrintable(r) {
					return l.fail(l.line, "invalid character '%c' (U+%04X)", r, r)
				}
				return l.fail(l.line, "invalid non-printable character U+%04X", r)
			}
		}
	}
	return l.emit(pyTokName, start, l.line)
}

// pyIDStart and pyIDContinue are Unicode's ID_Start and ID_Continue. Python uses the
// XID forms, which leave out a few compatibility characters: taking those as letters
// can only let a syntax error through.
func pyIDStart(r rune) bool {
	return r == '_' || unicode.IsLetter(r) || unicode.Is(unicode.Nl, r) || unicode.Is(unicode.Other_ID_Start, r)
}

func pyIDContinue(r rune) bool {
	return pyIDStart(r) || unicode.Is(unicode.Mn, r) || unicode.Is(unicode.Mc, r) || unicode.Is(unicode.Nd, r) ||
		unicode.Is(unicode.Pc, r) || unicode.Is(unicode.Other_ID_Continue, r)
}

// pyPrintable is str.isprintable for one character.
func pyPrintable(r rune) bool { return unicode.IsPrint(r) }

// numberEnd is CPython's verify_end_of_number: a letter can't touch a number, unless
// it starts a keyword (1if x else 2 still works).
func (l *pyLexer) numberEnd(kind string) bool {
	rest := l.src[l.cur:]
	for _, k := range []string{"and", "else", "for", "or", "not"} {
		if strings.HasPrefix(rest, k) && (len(rest) == len(k) || !pyIdentByte(int(rest[len(k)]))) {
			return true
		}
	}
	if strings.HasPrefix(rest, "if") || strings.HasPrefix(rest, "in") || strings.HasPrefix(rest, "is") {
		return true
	}
	if c := l.peek(); c >= 0 && c < 128 && pyIdentByte(c) {
		return l.fail(l.line, "invalid %s literal", kind)
	}
	return true
}

// decimalTail reads digits, single underscores between them.
func (l *pyLexer) decimalTail() bool {
	for {
		for pyDigit(l.peek()) {
			l.cur++
		}
		if l.peek() != '_' {
			return true
		}
		l.cur++
		if !pyDigit(l.peek()) {
			return l.fail(l.line, "invalid decimal literal")
		}
	}
}

// radix reads the digits after 0x, 0o or 0b.
func (l *pyLexer) radix(start int, kind string, digit func(int) bool) bool {
	l.cur++
	for {
		if l.peek() == '_' {
			l.cur++
		}
		if !digit(l.peek()) {
			if pyDigit(l.peek()) {
				return l.fail(l.line, "invalid digit '%c' in %s literal", l.peek(), kind)
			}
			return l.fail(l.line, "invalid %s literal", kind)
		}
		for digit(l.peek()) {
			l.cur++
		}
		if l.peek() != '_' {
			break
		}
	}
	if pyDigit(l.peek()) {
		return l.fail(l.line, "invalid digit '%c' in %s literal", l.peek(), kind)
	}
	if !l.numberEnd(kind) {
		return false
	}
	return l.emit(pyTokNumber, start, l.line)
}

func (l *pyLexer) number(start int) bool {
	if l.peek() != '0' {
		if !l.decimalTail() {
			return false
		}
		return l.afterDigits(start, false)
	}
	l.cur++
	switch l.peek() {
	case 'x', 'X':
		return l.radix(start, "hexadecimal", pyHexDigit)
	case 'o', 'O':
		return l.radix(start, "octal", func(c int) bool { return c >= '0' && c < '8' })
	case 'b', 'B':
		return l.radix(start, "binary", func(c int) bool { return c == '0' || c == '1' })
	}
	for {
		if l.peek() == '_' {
			l.cur++
			if !pyDigit(l.peek()) {
				return l.fail(l.line, "invalid decimal literal")
			}
		}
		if l.peek() != '0' {
			break
		}
		l.cur++
	}
	nonzero := pyDigit(l.peek())
	if nonzero && !l.decimalTail() {
		return false
	}
	return l.afterDigits(start, nonzero)
}

func (l *pyLexer) afterDigits(start int, leadingZeros bool) bool {
	switch c := l.peek(); {
	case c == '.':
		l.cur++
		return l.fraction(start)
	case c == 'e' || c == 'E':
		return l.exponent(start)
	case c == 'j' || c == 'J':
		return l.imaginary(start)
	case leadingZeros:
		return l.fail(l.line, "leading zeros in decimal integer literals are not permitted; use an 0o prefix for octal integers")
	}
	return l.numberDone(start, "decimal")
}

func (l *pyLexer) numberDone(start int, kind string) bool {
	if !l.numberEnd(kind) {
		return false
	}
	return l.emit(pyTokNumber, start, l.line)
}

func (l *pyLexer) fraction(start int) bool {
	if pyDigit(l.peek()) && !l.decimalTail() {
		return false
	}
	switch c := l.peek(); {
	case c == 'e' || c == 'E':
		return l.exponent(start)
	case c == 'j' || c == 'J':
		return l.imaginary(start)
	}
	return l.numberDone(start, "decimal")
}

func (l *pyLexer) exponent(start int) bool {
	l.cur++
	switch c := l.peek(); {
	case c == '+' || c == '-':
		l.cur++
		if !pyDigit(l.peek()) {
			return l.fail(l.line, "invalid decimal literal")
		}
	case !pyDigit(c):
		l.cur-- // that e belongs to whatever follows
		return l.numberDone(start, "decimal")
	}
	if !l.decimalTail() {
		return false
	}
	if c := l.peek(); c == 'j' || c == 'J' {
		return l.imaginary(start)
	}
	return l.numberDone(start, "decimal")
}

func (l *pyLexer) imaginary(start int) bool {
	l.cur++
	return l.numberDone(start, "imaginary")
}

// stringToken reads a plain string. The cursor is on its opening quote.
func (l *pyLexer) stringToken(start int) bool {
	quote := l.peek()
	first := l.line
	size, ends := 1, 0
	l.cur++
	if l.peek() == quote {
		l.cur++
		if l.peek() == quote {
			size = 3
			l.cur++
		} else {
			ends = 1 // the empty string
		}
	}
	escapedQuote := false
	for ends != size {
		c := l.peek()
		if c == pyEOF || (size == 1 && c == '\n') {
			detected := l.line
			if c == pyEOF {
				detected = l.eofLine()
			}
			if m := l.mode(); m != nil && int(m.quote) == quote && m.quoteSize == size {
				return l.fail(first, "f-string: expecting '}'")
			}
			switch {
			case size == 3:
				return l.fail(first, "unterminated triple-quoted string literal (detected at line %d)", detected)
			case escapedQuote:
				return l.fail(first, "unterminated string literal (detected at line %d); perhaps you escaped the end quote?", detected)
			}
			return l.fail(first, "unterminated string literal (detected at line %d)", detected)
		}
		l.read()
		if c == quote {
			ends++
			continue
		}
		ends = 0
		if c == '\\' {
			if l.peek() == quote {
				escapedQuote = true
			}
			l.read()
		}
	}
	return l.emit(pyTokString, start, first)
}

// fstringStart reads an f-string's opening quote, then its parts come through next.
func (l *pyLexer) fstringStart(start int, raw bool) bool {
	quote := l.src[l.cur]
	size := 1
	l.cur++
	if l.peek() == int(quote) && l.peekAt(1) == int(quote) {
		size = 3
		l.cur += 2
	}
	if len(l.modes)+1 >= pyMaxFStrings {
		return l.fail(l.line, "too many nested f-strings")
	}
	l.modes = append(l.modes, &pyFMode{quote: quote, quoteSize: size, raw: raw, line: l.line, fieldDepth: -1, inString: true})
	return l.emit(pyTokFStart, start, l.line)
}

// enterField leaves an f-string's text for a replacement field.
func (l *pyLexer) enterField(m *pyFMode) bool {
	m.fieldDepth++
	if m.fieldDepth >= pyMaxFieldDepth {
		return l.fail(l.line, "f-string: expressions nested too deeply")
	}
	m.inString, m.inSpec = false, false
	return true
}

// fstringPart reads f-string text, up to the next field or the closing quote.
func (l *pyLexer) fstringPart(m *pyFMode) bool {
	start, line := l.cur, l.line
	if l.peek() == '{' && l.peekAt(1) != '{' {
		return l.enterField(m)
	}
	closing := true
	for i := 0; i < m.quoteSize; i++ {
		if l.peekAt(i) != int(m.quote) {
			closing = false
			break
		}
	}
	if closing {
		l.cur += m.quoteSize
		l.modes = l.modes[:len(l.modes)-1]
		return l.emit(pyTokFEnd, start, line)
	}
	ends, unicodeEscape := 0, false
	for ends != m.quoteSize {
		inSpec := m.inSpec && m.fieldDepth >= 0
		c := l.peek()
		if c == pyEOF || (m.quoteSize == 1 && c == '\n') {
			if inSpec && c == '\n' {
				return l.fail(l.line, "f-string: newlines are not allowed in format specifiers for single quoted f-strings")
			}
			detected := l.line
			if c == pyEOF {
				detected = l.eofLine()
			}
			if m.quoteSize == 3 {
				return l.fail(m.line, "unterminated triple-quoted f-string literal (detected at line %d)", detected)
			}
			return l.fail(m.line, "unterminated f-string literal (detected at line %d)", detected)
		}
		l.read()
		if c == int(m.quote) {
			ends++
			continue
		}
		ends = 0
		switch c {
		case '{':
			if l.peek() != '{' || inSpec {
				l.cur--
				l.emit(pyTokFMiddle, start, line)
				return l.enterField(m)
			}
			l.cur++
			return l.emit(pyTokFMiddle, start, line)
		case '}':
			if unicodeEscape {
				return l.emit(pyTokFMiddle, start, line)
			}
			if l.peek() == '}' && !inSpec && m.depth == 0 {
				l.cur++
				return l.emit(pyTokFMiddle, start, line)
			}
			l.cur--
			m.inString, m.inSpec = false, false
			return l.emit(pyTokFMiddle, start, line)
		case '\\':
			next := l.peek()
			if next == '{' || next == '}' {
				continue
			}
			l.read()
			if !m.raw && next == 'N' && l.peek() == '{' {
				l.cur++
				unicodeEscape = true
			}
		}
	}
	l.cur -= m.quoteSize // the closing quote is a token of its own
	return l.emit(pyTokFMiddle, start, line)
}

var pyOps3 = []string{"**=", "//=", ">>=", "<<=", "..."}
var pyOps2 = []string{"!=", "<>", "->", ":=", "==", "<=", ">=", "**", "//", ">>", "<<", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "@="}

// punctuation reads an operator or bracket, keeping the brackets balanced.
func (l *pyLexer) punctuation(start int) bool {
	c := l.peek()
	m := l.mode()
	if m != nil && m.fieldDepth >= 0 && (c == ':' || c == '}' || c == '!' || c == '{') {
		cursor := m.depth
		if c != '{' {
			cursor--
		}
		if c == ':' && cursor == m.fieldDepth {
			l.cur++
			m.inString, m.inSpec = true, true
			return l.emit(pyTokOp, start, l.line)
		}
	}
	rest := l.src[l.cur:]
	for _, ops := range [][]string{pyOps3, pyOps2} {
		for _, op := range ops {
			if strings.HasPrefix(rest, op) {
				l.cur += len(op)
				return l.emit(pyTokOp, start, l.line)
			}
		}
	}
	l.cur++
	switch c {
	case '(', '[', '{':
		if len(l.open) >= pyMaxLevel {
			return l.fail(l.line, "too many nested parentheses")
		}
		l.open = append(l.open, pyBracket{byte(c), l.line})
		if m != nil {
			m.depth++
		}
	case ')', ']', '}':
		if m != nil && m.depth == 0 && c == '}' {
			return l.fail(l.line, "f-string: single '}' is not allowed")
		}
		if len(l.open) == 0 {
			return l.fail(l.line, "unmatched '%c'", c)
		}
		b := l.open[len(l.open)-1]
		l.open = l.open[:len(l.open)-1]
		if (b.c == '(' && c != ')') || (b.c == '[' && c != ']') || (b.c == '{' && c != '}') {
			if m != nil && b.c == '{' && m.depth-1 == m.fieldDepth {
				return l.fail(l.line, "f-string: unmatched '%c'", c)
			}
			if b.line != l.line {
				return l.fail(l.line, "closing parenthesis '%c' does not match opening parenthesis '%c' on line %d", c, b.c, b.line)
			}
			return l.fail(l.line, "closing parenthesis '%c' does not match opening parenthesis '%c'", c, b.c)
		}
		if m != nil {
			m.depth--
			if m.depth < 0 {
				return l.fail(l.line, "f-string: unmatched '%c'", c)
			}
			if c == '}' && m.depth == m.fieldDepth {
				m.fieldDepth--
				m.inString, m.inSpec = true, false
			}
		}
	}
	if !pyPrintable(rune(c)) {
		return l.fail(l.line, "invalid non-printable character U+%04X", c)
	}
	return l.emit(pyTokOp, start, l.line)
}

// ---------- the tree ----------

// pyNode is one node of Python's ast. kind is its class name; the fields hold what the
// checks read, and kids what ast.iter_child_nodes gives, in that order, without the
// leaves that have no children of their own (operators, contexts, aliases, a pattern's
// parts), since those can't change the order anything else is walked in.
type pyNode struct {
	kind      string
	line, end int // end only for statements
	semi      int // a simple statement's trailing ;, if there's one

	name     string   // a Name's id, Attribute's attr, keyword's arg, def's or class's name, ImportFrom's module
	op       string   // BinOp, UnaryOp and BoolOp: the operator
	ops      []string // Compare: the operators, by ast's class names
	constant string   // Constant: str, bytes, int, float, complex, True, False, None or Ellipsis
	str      string   // Constant: a str's value
	store    bool     // assigned to: ast's Store context
	paren    bool     // written inside brackets of its own
	level    int      // ImportFrom: its dots
	names    []pyAlias

	value      *pyNode // Attribute, Subscript, Starred, keyword, Expr, Assign, AnnAssign, UnaryOp's operand
	fn         *pyNode // Call's func
	slice      *pyNode // Subscript's
	test       *pyNode // If, While
	target     *pyNode // For, AugAssign, AnnAssign
	iter       *pyNode // For
	left       *pyNode // Compare, BinOp
	right      *pyNode // BinOp
	args       []*pyNode
	keywords   []*pyNode
	elts       []*pyNode // Tuple, List, Set, Delete; BoolOp's values; Compare's comparators; Assign's targets
	keys       []*pyNode // Dict: nil for a ** entry
	body       []*pyNode
	orelse     []*pyNode
	finalbody  []*pyNode
	handlers   []*pyNode
	decorators []*pyNode
	params     *pyParams

	kids []*pyNode
}

type pyAlias struct{ name, asname string }

// pyParams is what the checks read of a def's parameters.
type pyParams struct {
	positional, keywordOnly int
	varargs, kwargs         bool
}

func (n *pyNode) add(kids ...*pyNode) *pyNode {
	for _, k := range kids {
		if k != nil {
			n.kids = append(n.kids, k)
		}
	}
	return n
}

// pyWalk is ast.walk: breadth first.
func pyWalk(root *pyNode) []*pyNode {
	out := []*pyNode{root}
	for i := 0; i < len(out); i++ {
		out = append(out, out[i].kids...)
	}
	return out
}

// pyDump writes a tree as text, for comparing with what ast makes of the same source.
func pyDump(b *strings.Builder, n *pyNode) {
	fmt.Fprintf(b, "(%s %d", n.kind, n.line)
	if n.end != 0 {
		fmt.Fprintf(b, "-%d", n.end)
	}
	if n.name != "" {
		b.WriteString(" " + n.name)
	}
	if n.kind == "Constant" {
		b.WriteString(" " + n.constant)
		if n.constant == "str" {
			fmt.Fprintf(b, " %x", n.str)
		}
	}
	if n.store {
		b.WriteString(" store")
	}
	if n.op != "" {
		b.WriteString(" " + n.op)
	}
	if len(n.ops) > 0 {
		b.WriteString(" " + strings.Join(n.ops, ","))
	}
	for _, a := range n.names {
		b.WriteString(" " + a.name)
		if a.asname != "" {
			b.WriteString(":" + a.asname)
		}
	}
	if n.kind == "ImportFrom" {
		fmt.Fprintf(b, " .%d", n.level)
	}
	for _, k := range n.kids {
		b.WriteString(" ")
		pyDump(b, k)
	}
	b.WriteString(")")
}

// ---------- reading statements ----------

var pyKeywords = map[string]bool{
	"False": true, "None": true, "True": true, "and": true, "as": true, "assert": true, "async": true, "await": true,
	"break": true, "class": true, "continue": true, "def": true, "del": true, "elif": true, "else": true, "except": true,
	"finally": true, "for": true, "from": true, "global": true, "if": true, "import": true, "in": true, "is": true,
	"lambda": true, "nonlocal": true, "not": true, "or": true, "pass": true, "raise": true, "return": true, "try": true,
	"while": true, "with": true, "yield": true,
}

// pyFailed is a plain failure: the first pass only knows the tokens don't fit.
type pyFailed struct{}

// pyGaveUp ends a second pass that has been at it too long. The script is already
// known to be wrong by then; all that's lost is the exact words.
type pyGaveUp struct{}

const pyMaxTries = 200000

// pyMaxDepth is how deep an expression or elif chain may go without brackets. Each
// level is a Go stack frame here and in whatever walks the tree, and a stack overflow
// can't be recovered from. CPython stops well before this (about 6,000 unary operators
// or 10,000 attributes), so nothing it accepts is refused.
const pyMaxDepth = 20000

type pyParser struct {
	toks   []pyToken
	at     int
	far    int  // the furthest token looked at
	second bool // the second pass, which may say what's wrong
	peg    bool // the second pass: an operator with nothing readable after it isn't taken
	quiet  bool // a target that isn't one just fails
	tries  int
	depth  int // how deep the expression being read is, against pyMaxDepth
}

// pyParse reads Python source into a Module, as ast.parse does. A nil tree comes with
// the error.
func pyParse(src string) (*pyNode, *pySyntaxError) {
	if strings.Contains(src, "\x00") {
		return nil, &pySyntaxError{0, "source code string cannot contain null bytes"}
	}
	lx := pyLex(pyNormalize(src))
	p := &pyParser{toks: lx.toks}
	tree, err := p.pass(false)
	if tree != nil {
		return tree, nil
	}
	if err == nil {
		last := p.toks[p.far]
		_, err = p.pass(true)
		if err == nil {
			switch last.kind {
			case pyTokIndent:
				return nil, &pySyntaxError{last.line, "unexpected indent"}
			case pyTokDedent:
				return nil, &pySyntaxError{last.line, "unexpected unindent"}
			}
			err = &pySyntaxError{last.line, "invalid syntax"}
		}
	}
	// As CPython does, go on through the rest of the tokens: an error the tokenizer
	// finds there is the one Python reports, unless the parser got that far anyway or
	// it's inside an f-string.
	if err == p.toks[len(p.toks)-1].err || len(lx.modes) > 0 {
		return nil, err
	}
	if lx.hard != nil {
		return nil, lx.hard
	}
	if lx.unclosed != nil && p.toks[p.far].line > lx.unclosed.line {
		return nil, lx.unclosed
	}
	return nil, err
}

func (p *pyParser) pass(second bool) (tree *pyNode, err *pySyntaxError) {
	p.at, p.second, p.peg, p.depth = 0, second, second, 0
	defer func() {
		switch r := recover().(type) {
		case nil:
		case *pySyntaxError:
			tree, err = nil, r
		case pyFailed, pyGaveUp:
			tree = nil
		default:
			panic(r)
		}
	}()
	module := &pyNode{kind: "Module"}
	for p.tok().kind != pyTokEnd {
		module.body = append(module.body, p.statement()...)
	}
	return module.add(module.body...), nil
}

// tok is the current token. Reaching where the tokenizer stopped raises its error.
func (p *pyParser) tok() *pyToken { return p.look(0) }

func (p *pyParser) look(n int) *pyToken {
	i := min(p.at+n, len(p.toks)-1)
	if i > p.far {
		p.far = i
	}
	t := &p.toks[i]
	if t.kind == pyTokStop {
		panic(t.err)
	}
	return t
}

func (p *pyParser) next() *pyToken {
	t := p.tok()
	if t.kind != pyTokEnd {
		p.at++
	}
	return t
}

func (p *pyParser) fail() { panic(pyFailed{}) }

// say stops with what's wrong in the second pass. In the first it's a plain failure.
func (p *pyParser) say(line int, format string, args ...any) {
	if p.second {
		panic(&pySyntaxError{line, fmt.Sprintf(format, args...)})
	}
	p.fail()
}

// sayLast is say at the furthest token looked at, which is where a bare
// RAISE_SYNTAX_ERROR in CPython's grammar points.
func (p *pyParser) sayLast(format string, args ...any) {
	p.say(p.toks[p.far].line, format, args...)
}

// deeper counts a level against pyMaxDepth. It's a syntax error past that.
func (p *pyParser) deeper(line int) {
	if p.depth++; p.depth > pyMaxDepth {
		panic(&pySyntaxError{line, "too deeply nested"})
	}
}

// try runs f, and on a plain failure puts the parser back where it was.
func (p *pyParser) try(f func()) (ok bool) {
	at, depth := p.at, p.depth
	if p.peg { // only an error pass goes over the same tokens again and again
		if p.tries++; p.tries > pyMaxTries {
			panic(pyGaveUp{})
		}
	}
	defer func() {
		if r := recover(); r != nil {
			if _, plain := r.(pyFailed); !plain {
				panic(r)
			}
			p.at, p.depth, ok = at, depth, false
		}
	}()
	f()
	return true
}

func (t *pyToken) isOp(s string) bool   { return t.kind == pyTokOp && t.text == s }
func (t *pyToken) isWord(s string) bool { return t.kind == pyTokName && t.text == s }
func (t *pyToken) isIdent() bool        { return t.kind == pyTokName && !pyKeywords[t.text] }

func (p *pyParser) op(s string) bool   { return p.tok().isOp(s) }
func (p *pyParser) word(s string) bool { return p.tok().isWord(s) }

func (p *pyParser) eatOp(s string) bool {
	if p.op(s) {
		p.at++
		return true
	}
	return false
}

func (p *pyParser) eatWord(s string) bool {
	if p.word(s) {
		p.at++
		return true
	}
	return false
}

func (p *pyParser) wantOp(s string) {
	if !p.eatOp(s) {
		p.fail()
	}
}

func (p *pyParser) wantWord(s string) {
	if !p.eatWord(s) {
		p.fail()
	}
}

func (p *pyParser) wantKind(k pyTokenKind) {
	if p.tok().kind != k {
		p.fail()
	}
	p.at++
}

func (p *pyParser) ident() string {
	t := p.tok()
	if !t.isIdent() {
		p.fail()
	}
	p.at++
	return t.text
}

// lastEnd is where the last token read ends.
func (p *pyParser) lastEnd() int { return p.toks[p.at-1].end }

// colon wants the : of a statement that only names it if the line just ends.
func (p *pyParser) colon() {
	if p.eatOp(":") {
		return
	}
	if p.tok().kind == pyTokNewline {
		p.sayLast("expected ':'")
	}
	p.fail()
}

// forced wants a token CPython's grammar insists on, and says so in either pass.
func (p *pyParser) forced(s string) {
	if !p.eatOp(s) {
		panic(&pySyntaxError{p.tok().line, "expected '" + s + "'"})
	}
}

func pyEndOf(blocks ...[]*pyNode) int {
	for i := len(blocks) - 1; i >= 0; i-- {
		if b := blocks[i]; len(b) > 0 {
			return max(b[len(b)-1].end, b[len(b)-1].semi)
		}
	}
	return 0
}

func (p *pyParser) block(what string, line int) []*pyNode {
	if p.tok().kind != pyTokNewline {
		return p.simpleStatements()
	}
	p.at++
	if p.tok().kind != pyTokIndent {
		p.sayLast("expected an indented block after %s on line %d", what, line)
		p.fail()
	}
	p.at++
	var body []*pyNode
	for {
		body = append(body, p.statement()...)
		if p.tok().kind == pyTokDedent {
			p.at++
			return body
		}
	}
}

func (p *pyParser) statement() []*pyNode {
	t := p.tok()
	if t.isOp("@") {
		return []*pyNode{p.decorated()}
	}
	if t.kind == pyTokName {
		switch t.text {
		case "if":
			return []*pyNode{p.ifStatement()}
		case "while":
			return []*pyNode{p.whileStatement()}
		case "for":
			return []*pyNode{p.forStatement("For", t.line)}
		case "try":
			return []*pyNode{p.tryStatement()}
		case "with":
			return []*pyNode{p.withStatement("With", t.line)}
		case "def":
			return []*pyNode{p.funcDef("FunctionDef", t.line, nil)}
		case "class":
			return []*pyNode{p.classDef(nil)}
		case "async":
			p.at++
			switch {
			case p.word("def"):
				return []*pyNode{p.funcDef("AsyncFunctionDef", t.line, nil)}
			case p.word("for"):
				return []*pyNode{p.forStatement("AsyncFor", t.line)}
			case p.word("with"):
				return []*pyNode{p.withStatement("AsyncWith", t.line)}
			}
			p.fail()
		case "match":
			if n := p.matchStatement(); n != nil {
				return []*pyNode{n}
			}
		}
	}
	return p.simpleStatements()
}

func (p *pyParser) decorated() *pyNode {
	var decorators []*pyNode
	for p.eatOp("@") {
		decorators = append(decorators, p.namedExpression())
		p.wantKind(pyTokNewline)
	}
	t := p.tok()
	switch {
	case t.isWord("def"):
		return p.funcDef("FunctionDef", t.line, decorators)
	case t.isWord("class"):
		return p.classDef(decorators)
	case t.isWord("async"):
		p.at++
		if p.word("def") {
			return p.funcDef("AsyncFunctionDef", t.line, decorators)
		}
	}
	p.fail()
	return nil
}

func (p *pyParser) ifStatement() *pyNode {
	t := p.next()
	test := p.namedExpression()
	p.colon()
	n := &pyNode{kind: "If", line: t.line, test: test}
	n.body = p.block("'"+t.text+"' statement", t.line)
	if p.word("elif") {
		p.deeper(t.line)
		n.orelse = []*pyNode{p.ifStatement()}
		p.depth--
	} else if p.word("else") {
		n.orelse = p.elseBlock()
	}
	n.end = pyEndOf(n.body, n.orelse)
	return n.add(test).add(n.body...).add(n.orelse...)
}

func (p *pyParser) elseBlock() []*pyNode {
	t := p.next()
	p.forced(":")
	return p.block("'else' statement", t.line)
}

func (p *pyParser) whileStatement() *pyNode {
	t := p.next()
	test := p.namedExpression()
	p.colon()
	n := &pyNode{kind: "While", line: t.line, test: test}
	n.body = p.block("'while' statement", t.line)
	if p.word("else") {
		n.orelse = p.elseBlock()
	}
	n.end = pyEndOf(n.body, n.orelse)
	return n.add(test).add(n.body...).add(n.orelse...)
}

func (p *pyParser) forStatement(kind string, line int) *pyNode {
	t := p.next()
	at := p.at
	target := p.forTarget()
	if target == nil {
		if p.second {
			p.at = at
			p.badForTarget()
		}
		p.fail()
	}
	iter := p.starExpressions()
	p.colon()
	n := &pyNode{kind: kind, line: line, target: target, iter: iter}
	n.body = p.block("'for' statement", t.line)
	if p.word("else") {
		n.orelse = p.elseBlock()
	}
	n.end = pyEndOf(n.body, n.orelse)
	return n.add(target, iter).add(n.body...).add(n.orelse...)
}

// forTarget reads a target and its `in`, nil if there's no such thing here.
func (p *pyParser) forTarget() (target *pyNode) {
	saved := p.quiet
	p.quiet = true
	defer func() { p.quiet = saved }()
	if p.try(func() {
		target = p.targetList()
		p.wantWord("in")
	}) {
		return target
	}
	return nil
}

// badForTarget is CPython's invalid_for_target: what's after for, read as an expression.
func (p *pyParser) badForTarget() {
	var e *pyNode
	if p.try(func() { e = p.starExpressions() }) {
		if bad := pyInvalidTarget(e, "for"); bad != nil {
			p.say(bad.line, "cannot assign to %s", pyExprName(bad))
		}
	}
}

func (p *pyParser) tryStatement() *pyNode {
	t := p.next()
	p.forced(":")
	n := &pyNode{kind: "Try", line: t.line}
	n.body = p.block("'try' statement", t.line)
	for p.word("except") {
		h := p.next()
		star := p.eatOp("*")
		if len(n.handlers) > 0 && star != (n.kind == "TryStar") {
			if p.second {
				p.tryHandlerHeader()
			}
			p.say(h.line, "cannot have both 'except' and 'except*' on the same 'try'")
		}
		if star {
			n.kind = "TryStar"
		}
		what := "'except' statement"
		if star {
			what = "'except*' statement"
		}
		handler := &pyNode{kind: "ExceptHandler", line: h.line}
		if !p.op(":") {
			if star && p.tok().kind == pyTokNewline {
				p.sayLast("expected one or more exception types")
			}
			if p.tok().kind == pyTokNewline {
				p.sayLast("expected ':'")
			}
			kind := p.expression()
			handler.add(kind)
			if p.op(",") && p.second {
				p.multipleExceptionTypes(kind)
			}
			if p.eatWord("as") {
				handler.name = p.ident()
			}
		} else if star {
			p.sayLast("expected one or more exception types")
		}
		p.colon()
		handler.body = p.block(what, h.line)
		handler.end = pyEndOf(handler.body)
		n.handlers = append(n.handlers, handler.add(handler.body...))
	}
	if len(n.handlers) > 0 && p.word("else") {
		n.orelse = p.elseBlock()
	}
	if p.word("finally") {
		f := p.next()
		p.forced(":")
		n.finalbody = p.block("'finally' statement", f.line)
	}
	if len(n.handlers) == 0 && len(n.finalbody) == 0 {
		p.sayLast("expected 'except' or 'finally' block")
		p.fail()
	}
	n.end = pyEndOf(n.body, n.handlers, n.orelse, n.finalbody)
	return n.add(n.body...).add(n.handlers...).add(n.orelse...).add(n.finalbody...)
}

// tryHandlerHeader reads the rest of an except line, so the message about mixing the
// two kinds only comes if the line itself is fine.
func (p *pyParser) tryHandlerHeader() {
	if !p.op(":") {
		p.expression()
		if p.eatWord("as") {
			p.ident()
		}
	}
	p.wantOp(":")
}

func (p *pyParser) multipleExceptionTypes(first *pyNode) {
	at := p.at
	if p.try(func() {
		p.wantOp(",")
		p.expression()
		for p.eatOp(",") {
			if p.op(":") || p.word("as") {
				break
			}
			p.expression()
		}
		if p.eatWord("as") {
			p.ident()
		}
		p.wantOp(":")
	}) {
		p.say(first.line, "multiple exception types must be parenthesized")
	}
	p.at = at
}

func (p *pyParser) withStatement(kind string, line int) *pyNode {
	t := p.next()
	n := &pyNode{kind: kind, line: line}
	var items []*pyNode
	bracketed := p.op("(") && p.try(func() {
		p.at++
		for {
			items = append(items, p.withItem())
			if !p.eatOp(",") || p.op(")") {
				break
			}
		}
		p.wantOp(")")
		if !p.op(":") {
			p.fail()
		}
	})
	if !bracketed {
		items = nil
		for {
			items = append(items, p.withItem())
			if !p.eatOp(",") {
				break
			}
		}
	}
	p.colon()
	n.body = p.block("'with' statement", t.line)
	n.end = pyEndOf(n.body)
	return n.add(items...).add(n.body...)
}

func (p *pyParser) withItem() *pyNode {
	item := &pyNode{kind: "withitem"}
	context := p.expression()
	item.add(context)
	if p.eatWord("as") {
		target := p.starTarget()
		p.assignTo(target)
		if t := p.tok(); !t.isOp(",") && !t.isOp(")") && !t.isOp(":") {
			p.fail()
		}
		item.add(target)
	}
	return item
}

// typeParams reads [T: int = str, *Ts, **P] after a def, class or type name.
func (p *pyParser) typeParams() []*pyNode {
	if !p.op("[") {
		return nil
	}
	if p.look(1).isOp("]") {
		p.say(p.tok().line, "Type parameter list cannot be empty")
	}
	p.at++
	var out []*pyNode
	for {
		kind, line := "TypeVar", p.tok().line
		if p.eatOp("*") {
			kind = "TypeVarTuple"
		} else if p.eatOp("**") {
			kind = "ParamSpec"
		}
		n := &pyNode{kind: kind, line: line, name: p.ident()}
		if kind == "TypeVar" && p.eatOp(":") {
			n.add(p.expression())
		}
		if p.eatOp("=") {
			if kind == "TypeVarTuple" {
				n.add(p.starExpression())
			} else {
				n.add(p.expression())
			}
		}
		out = append(out, n)
		if !p.eatOp(",") || p.op("]") {
			break
		}
	}
	p.wantOp("]")
	return out
}

func (p *pyParser) funcDef(kind string, line int, decorators []*pyNode) *pyNode {
	t := p.next()
	n := &pyNode{kind: kind, line: line, decorators: decorators, name: p.ident()}
	var types []*pyNode
	p.try(func() { types = p.typeParams() })
	if !p.op("(") {
		p.say(p.tok().line, "expected '('")
	}
	p.at++
	params := p.parameters(")")
	p.wantOp(")")
	var returns *pyNode
	if p.op("->") {
		at := p.at
		p.at++
		if returns = p.operand(p.expression); returns == nil {
			p.at = at
		}
	}
	p.forced(":")
	n.body = p.block("function definition", t.line)
	n.end = pyEndOf(n.body)
	n.params = params.params
	return n.add(params).add(n.body...).add(decorators...).add(returns).add(types...)
}

// parameters reads a def's or a lambda's, up to closer.
func (p *pyParser) parameters(closer string) *pyNode {
	n := &pyNode{kind: "arguments", params: &pyParams{}}
	annotated := closer == ")"
	var positional, keywordOnly, keywordDefaults, defaults []*pyNode
	var varargs, kwargs *pyNode
	slash, star := false, false
	for !p.op(closer) {
		t := p.tok()
		switch {
		case t.isOp("/"):
			if len(positional) == 0 {
				if p.look(1).isOp(",") {
					p.say(t.line, "at least one argument must precede /")
				}
				p.fail()
			}
			if slash {
				p.say(t.line, "/ may appear only once")
			}
			if star {
				p.say(t.line, "/ must be ahead of *")
			}
			slash = true
			p.at++
		case t.isOp("*"):
			if u := p.look(1); star && (u.isIdent() || u.isOp(",")) {
				p.say(t.line, "* argument may appear only once")
			}
			if star {
				p.fail()
			}
			star = true
			p.at++
			if p.op(closer) || (p.op(",") && (p.look(1).isOp(closer) || p.look(1).isOp("**"))) {
				p.say(t.line, "named arguments must follow bare *")
			}
			if !p.op(",") {
				varargs = p.parameter(annotated, true)
				if p.op("=") {
					p.say(p.tok().line, "var-positional argument cannot have default value")
				}
			}
		case t.isOp("**"):
			p.at++
			kwargs = p.parameter(annotated, false)
			if p.op("=") {
				p.say(p.tok().line, "var-keyword argument cannot have default value")
			}
			p.eatOp(",")
			if !p.op(closer) {
				if u := p.tok(); u.isIdent() || u.isOp("*") || u.isOp("**") || u.isOp("/") {
					p.say(u.line, "arguments cannot follow var-keyword argument")
				}
				p.fail()
			}
			continue
		default:
			a := p.parameter(annotated, false)
			var value *pyNode
			if p.eatOp("=") {
				if u := p.tok(); u.isOp(closer) || u.isOp(",") {
					p.say(p.toks[p.at-1].line, "expected default value expression")
				}
				value = p.expression()
			}
			if star {
				keywordOnly, keywordDefaults = append(keywordOnly, a), append(keywordDefaults, value)
				break
			}
			positional = append(positional, a)
			if value != nil {
				defaults = append(defaults, value)
			} else if len(defaults) > 0 {
				if u := p.tok(); u.isOp(",") || u.isOp(closer) {
					p.say(a.line, "parameter without a default follows parameter with a default")
				}
				p.fail()
			}
		}
		if !p.eatOp(",") {
			break
		}
	}
	n.params.positional, n.params.keywordOnly = len(positional), len(keywordOnly)
	n.params.varargs, n.params.kwargs = varargs != nil, kwargs != nil
	return n.add(positional...).add(varargs).add(keywordOnly...).add(keywordDefaults...).add(kwargs).add(defaults...)
}

func (p *pyParser) parameter(annotated, star bool) *pyNode {
	t := p.tok()
	if t.isOp("(") {
		p.bracketedParameters(annotated)
		p.fail()
	}
	a := &pyNode{kind: "arg", line: t.line, name: p.ident()}
	if annotated && p.eatOp(":") {
		if star && p.op("*") {
			a.add(p.starExpression())
		} else {
			a.add(p.expression())
		}
	}
	return a
}

// bracketedParameters is a list of parameters in brackets, which Python 2 allowed.
func (p *pyParser) bracketedParameters(annotated bool) {
	t := p.tok()
	if p.second && p.try(func() {
		p.at++
		for {
			p.parameter(annotated, false)
			if !p.eatOp(",") || p.op(")") {
				break
			}
		}
		p.wantOp(")")
	}) {
		if annotated {
			p.say(t.line, "Function parameters cannot be parenthesized")
		}
		p.say(t.line, "Lambda expression parameters cannot be parenthesized")
	}
}

func (p *pyParser) classDef(decorators []*pyNode) *pyNode {
	t := p.next()
	n := &pyNode{kind: "ClassDef", line: t.line, decorators: decorators, name: p.ident()}
	types := p.typeParams()
	if p.eatOp("(") {
		p.callArguments(n)
	}
	p.colon()
	n.body = p.block("class definition", t.line)
	n.end = pyEndOf(n.body)
	return n.add(n.args...).add(n.keywords...).add(n.body...).add(decorators...).add(types...)
}

// matchStatement reads a match statement, or gives nil if the line isn't one: match is
// an ordinary name unless the whole form is there.
func (p *pyParser) matchStatement() *pyNode {
	t := p.tok()
	var subject *pyNode
	if !p.try(func() {
		p.at++
		subject = p.subject()
		p.colon()
		p.wantKind(pyTokNewline)
		if p.tok().kind != pyTokIndent {
			p.sayLast("expected an indented block after 'match' statement on line %d", t.line)
			p.fail()
		}
		p.at++
		if !p.word("case") {
			p.fail()
		}
	}) {
		return nil
	}
	n := &pyNode{kind: "Match", line: t.line}
	n.add(subject)
	for {
		n.body = append(n.body, p.caseBlock())
		if p.tok().kind == pyTokDedent {
			p.at++
			break
		}
	}
	n.end = pyEndOf(n.body)
	return n.add(n.body...)
}

func (p *pyParser) subject() *pyNode {
	line := p.tok().line
	first := p.starNamedExpression()
	if !p.op(",") {
		if first.kind == "Starred" {
			p.fail()
		}
		return first
	}
	elts := []*pyNode{first}
	for p.eatOp(",") {
		if p.op(":") {
			break
		}
		elts = append(elts, p.starNamedExpression())
	}
	return (&pyNode{kind: "Tuple", line: line, elts: elts}).add(elts...)
}

// caseBlock skips a case's pattern, which holds nothing the checks read, to its guard
// and body.
func (p *pyParser) caseBlock() *pyNode {
	t := p.next()
	if !t.isWord("case") {
		p.fail()
	}
	n := &pyNode{kind: "match_case"}
	depth, pattern := 0, false
	for {
		u := p.tok()
		if (u.kind == pyTokNewline || u.kind == pyTokEnd) && depth == 0 {
			if pattern {
				p.sayLast("expected ':'")
			}
			p.fail()
		}
		if depth == 0 && (u.isOp(":") || u.isWord("if")) {
			break
		}
		switch {
		case u.isOp("(") || u.isOp("[") || u.isOp("{"):
			depth++
		case u.isOp(")") || u.isOp("]") || u.isOp("}"):
			depth--
		}
		pattern = true
		p.at++
	}
	if !pattern {
		p.fail()
	}
	if p.eatWord("if") {
		n.add(p.namedExpression())
	}
	p.colon()
	n.body = p.block("'case' statement", t.line)
	n.end = pyEndOf(n.body)
	return n.add(n.body...)
}

func (p *pyParser) simpleStatements() []*pyNode {
	var out []*pyNode
	for {
		out = append(out, p.simpleStatement())
		if !p.eatOp(";") {
			break
		}
		if p.tok().kind == pyTokNewline {
			out[len(out)-1].semi = p.lastEnd() // a trailing ; counts for the end of its block
			break
		}
	}
	p.wantKind(pyTokNewline)
	return out
}

func (p *pyParser) simpleStatement() *pyNode {
	t := p.tok()
	if t.kind == pyTokName {
		switch t.text {
		case "pass", "break", "continue":
			p.at++
			return &pyNode{kind: strings.ToUpper(t.text[:1]) + t.text[1:], line: t.line, end: t.line}
		case "return":
			p.at++
			n := &pyNode{kind: "Return", line: t.line}
			if !p.statementEnds() {
				n.add(p.starExpressions())
			}
			n.end = p.lastEnd()
			return n
		case "raise":
			p.at++
			n := &pyNode{kind: "Raise", line: t.line}
			if !p.statementEnds() {
				n.add(p.expression())
				if p.eatWord("from") {
					n.add(p.expression())
				}
			}
			n.end = p.lastEnd()
			return n
		case "global", "nonlocal":
			p.at++
			p.ident()
			for p.eatOp(",") {
				p.ident()
			}
			return &pyNode{kind: strings.ToUpper(t.text[:1]) + t.text[1:], line: t.line, end: p.lastEnd()}
		case "assert":
			p.at++
			n := &pyNode{kind: "Assert", line: t.line}
			n.add(p.expression())
			if p.eatOp(",") {
				n.add(p.expression())
			}
			n.end = p.lastEnd()
			return n
		case "del":
			return p.deleteStatement()
		case "import":
			return p.importStatement()
		case "from":
			return p.fromStatement()
		case "type":
			if u := p.look(1); u.isIdent() && (p.look(2).isOp("=") || p.look(2).isOp("[")) {
				return p.typeAlias()
			}
		}
	}
	return p.expressionStatement()
}

func (p *pyParser) statementEnds() bool {
	t := p.tok()
	return t.kind == pyTokNewline || t.isOp(";")
}

func (p *pyParser) typeAlias() *pyNode {
	t := p.next()
	name := &pyNode{kind: "Name", line: p.tok().line, name: p.ident(), store: true}
	types := p.typeParams()
	p.wantOp("=")
	value := p.expression()
	n := &pyNode{kind: "TypeAlias", line: t.line, end: p.lastEnd()}
	return n.add(name).add(types...).add(value)
}

func (p *pyParser) deleteStatement() *pyNode {
	t := p.next()
	n := &pyNode{kind: "Delete", line: t.line}
	at := p.at
	if !p.try(func() {
		for {
			target := p.binary(0)
			if pyInvalidTarget(target, "del") != nil {
				p.fail()
			}
			n.elts = append(n.elts, target)
			if !p.eatOp(",") || p.statementEnds() {
				break
			}
		}
		if !p.statementEnds() {
			p.fail()
		}
	}) {
		var e *pyNode
		if p.second && p.try(func() { e = p.starExpressions() }) {
			if bad := pyInvalidTarget(e, "del"); bad != nil {
				p.say(bad.line, "cannot delete %s", pyExprName(bad))
			}
		}
		p.at = at
		p.fail()
	}
	n.end = p.lastEnd()
	return n.add(n.elts...)
}

func (p *pyParser) dottedName() string {
	name := p.ident()
	for p.op(".") {
		p.at++
		name += "." + p.ident()
	}
	return name
}

func (p *pyParser) importStatement() *pyNode {
	t := p.next()
	if p.tok().kind == pyTokNewline {
		p.sayLast("Expected one or more names after 'import'")
	}
	n := &pyNode{kind: "Import", line: t.line}
	for {
		a := pyAlias{name: p.dottedName()}
		if p.eatWord("as") {
			a.asname = p.ident()
		}
		n.names = append(n.names, a)
		if !p.eatOp(",") {
			break
		}
	}
	if p.word("from") {
		p.say(t.line, "Did you mean to use 'from ... import ...' instead?")
	}
	n.end = p.lastEnd()
	return n
}

func (p *pyParser) fromStatement() *pyNode {
	t := p.next()
	n := &pyNode{kind: "ImportFrom", line: t.line}
	for {
		if p.eatOp(".") {
			n.level++
		} else if p.eatOp("...") {
			n.level += 3
		} else {
			break
		}
	}
	if !p.word("import") {
		n.name = p.dottedName()
	} else if n.level == 0 {
		p.fail()
	}
	p.wantWord("import")
	switch {
	case p.eatOp("*"):
		n.names = []pyAlias{{name: "*"}}
	case p.eatOp("("):
		for {
			n.names = append(n.names, p.fromName())
			if !p.eatOp(",") || p.op(")") {
				break
			}
		}
		p.wantOp(")")
	default:
		if p.tok().kind == pyTokNewline {
			p.sayLast("Expected one or more names after 'import'")
		}
		for {
			n.names = append(n.names, p.fromName())
			if !p.eatOp(",") {
				break
			}
			if p.tok().kind == pyTokNewline {
				p.sayLast("trailing comma not allowed without surrounding parentheses")
				p.fail()
			}
		}
	}
	n.end = p.lastEnd()
	return n
}

func (p *pyParser) fromName() pyAlias {
	a := pyAlias{name: p.ident()}
	if p.eatWord("as") {
		a.asname = p.ident()
	}
	return a
}

var pyAugmented = map[string]bool{"+=": true, "-=": true, "*=": true, "/=": true, "%=": true, "&=": true, "|=": true,
	"^=": true, "<<=": true, ">>=": true, "**=": true, "//=": true, "@=": true}

func (p *pyParser) rightSide() *pyNode {
	if p.word("yield") {
		return p.yieldExpression()
	}
	return p.starExpressions()
}

// expressionStatement reads an assignment, or a bare expression.
func (p *pyParser) expressionStatement() *pyNode {
	if p.second {
		p.invalidAssignment()
	}
	return p.assignmentOrExpression()
}

// invalidAssignment does what CPython's assignment rule does in the second pass, up to
// the end of invalid_assignment: an assignment that reads goes through, checks on. One
// that doesn't is read as a list of expressions, which is how a stray = in it gets
// named: that goes on past a missing comma.
func (p *pyParser) invalidAssignment() {
	at := p.at
	defer func() { p.at = at }()
	p.quiet = true
	assigns := p.try(func() {
		if k := p.assignmentOrExpression().kind; k != "Assign" && k != "AnnAssign" && k != "AugAssign" {
			p.fail()
		}
	})
	p.quiet = false
	if assigns {
		return
	}
	p.at = at
	p.try(func() {
		p.starNamedExpression()
		p.wantOp(",")
		for {
			before := p.at
			if !p.try(func() {
				for {
					p.starNamedExpression()
					if !p.eatOp(",") || !p.startsExpression() {
						break
					}
				}
			}) || p.at == before {
				return
			}
		}
	})
}

func (p *pyParser) assignmentOrExpression() *pyNode {
	t := p.tok()
	first := p.rightSide()
	u := p.tok()
	switch {
	case u.isOp(":"):
		return p.annotated(first, t.line)
	case u.isOp("="):
		return p.assignment(first, t.line)
	case u.kind == pyTokOp && pyAugmented[u.text]:
		switch {
		case first.kind == "Name" || first.kind == "Attribute" || first.kind == "Subscript":
		default:
			if p.second {
				p.at++
				if p.try(func() { p.rightSide() }) {
					p.say(first.line, "'%s' is an illegal expression for augmented assignment", pyExprName(first))
				}
			}
			p.fail()
		}
		p.at++
		first.store = true
		value := p.rightSide()
		n := &pyNode{kind: "AugAssign", line: t.line, end: p.lastEnd(), target: first, value: value}
		return n.add(first, value)
	}
	n := &pyNode{kind: "Expr", line: t.line, end: p.lastEnd(), value: first}
	return n.add(first)
}

func (p *pyParser) annotated(target *pyNode, line int) *pyNode {
	switch {
	case target.kind == "Name" || target.kind == "Attribute" || target.kind == "Subscript":
	case target.kind == "Tuple" || target.kind == "List":
		if p.second {
			p.at++
			if p.try(func() { p.expression() }) {
				p.say(target.line, "only single target (not %s) can be annotated", strings.ToLower(target.kind))
			}
		}
		p.fail()
	default:
		if p.second {
			p.at++
			if p.try(func() { p.expression() }) {
				p.say(target.line, "illegal target for annotation")
			}
		}
		p.fail()
	}
	p.at++
	target.store = true
	annotation := p.expression()
	n := &pyNode{kind: "AnnAssign", line: line, target: target}
	n.add(target, annotation)
	if p.eatOp("=") {
		n.value = p.rightSide()
		n.add(n.value)
	}
	n.end = p.lastEnd()
	return n
}

func (p *pyParser) assignment(first *pyNode, line int) *pyNode {
	n := &pyNode{kind: "Assign", line: line}
	cur := first
	for p.op("=") {
		p.assignFrom(cur)
		n.elts = append(n.elts, cur)
		p.at++
		cur = p.rightSide()
	}
	n.value, n.end = cur, p.lastEnd()
	return n.add(n.elts...).add(cur)
}

// assignFrom makes an expression a target, the = after it still to be read.
func (p *pyParser) assignFrom(target *pyNode) {
	if target.kind == "Yield" || target.kind == "YieldFrom" {
		p.sayLast("assignment to yield expression not possible")
		p.fail()
	}
	if bad := pyInvalidTarget(target, "assign"); bad != nil {
		if p.quiet {
			p.fail()
		}
		p.say(bad.line, "cannot assign to %s", pyExprName(bad))
	}
	pySetStore(target)
}

// followedByValue is at an =: a simple expression comes next, then no further = or :=.
func (p *pyParser) followedByValue() bool {
	at := p.at
	defer func() { p.at = at }()
	return p.try(func() {
		p.wantOp("=")
		p.binary(0)
		if p.op("=") || p.op(":=") {
			p.fail()
		}
	})
}

// pyBitwiseLevel says an expression would have been read whole by bitwise_or, the rule
// CPython's messages about = use.
func pyBitwiseLevel(e *pyNode) bool {
	if e.paren {
		return true
	}
	switch e.kind {
	case "Compare", "BoolOp", "IfExp", "Lambda", "NamedExpr":
		return false
	case "UnaryOp":
		return e.op != "Not"
	}
	return true
}

// pyInvalidTarget is _PyPegen_get_invalid_target: the first part of e that can't be
// assigned to, nil if all of it can. use is "assign", "del" or "for", where `a in b`
// was read as a comparison, so its left side is the target.
func pyInvalidTarget(e *pyNode, use string) *pyNode {
	switch e.kind {
	case "List", "Tuple":
		for _, x := range e.elts {
			if bad := pyInvalidTarget(x, use); bad != nil {
				return bad
			}
		}
		return nil
	case "Starred":
		if use == "del" {
			return e
		}
		return pyInvalidTarget(e.value, use)
	case "Compare":
		if use == "for" {
			if e.ops[0] == "In" {
				return pyInvalidTarget(e.left, use)
			}
			return nil
		}
	case "Name", "Subscript", "Attribute":
		return nil
	}
	return e
}

func pySetStore(e *pyNode) {
	e.store = true
	switch e.kind {
	case "List", "Tuple":
		for _, x := range e.elts {
			pySetStore(x)
		}
	case "Starred":
		pySetStore(e.value)
	}
}

// pyExprName is _PyPegen_get_expr_name.
func pyExprName(e *pyNode) string {
	switch e.kind {
	case "Attribute":
		return "attribute"
	case "Subscript":
		return "subscript"
	case "Starred":
		return "starred"
	case "Name":
		return "name"
	case "List":
		return "list"
	case "Tuple":
		return "tuple"
	case "Lambda":
		return "lambda"
	case "Call":
		return "function call"
	case "BoolOp", "BinOp", "UnaryOp":
		return "expression"
	case "GeneratorExp":
		return "generator expression"
	case "Yield", "YieldFrom":
		return "yield expression"
	case "Await":
		return "await expression"
	case "ListComp":
		return "list comprehension"
	case "SetComp":
		return "set comprehension"
	case "DictComp":
		return "dict comprehension"
	case "Dict":
		return "dict literal"
	case "Set":
		return "set display"
	case "JoinedStr", "FormattedValue":
		return "f-string expression"
	case "Compare":
		return "comparison"
	case "IfExp":
		return "conditional expression"
	case "NamedExpr":
		return "named expression"
	case "Constant":
		switch e.constant {
		case "None", "True", "False":
			return e.constant
		case "Ellipsis":
			return "ellipsis"
		}
		return "literal"
	}
	return "expression"
}

// assignTo checks a target read as an expression and marks it.
func (p *pyParser) assignTo(e *pyNode) {
	if bad := pyInvalidTarget(e, "assign"); bad != nil {
		if p.quiet {
			p.fail()
		}
		p.say(bad.line, "cannot assign to %s", pyExprName(bad))
	}
	pySetStore(e)
}

func (p *pyParser) starTarget() *pyNode {
	t := p.tok()
	if t.isOp("*") {
		p.at++
		value := p.binary(0)
		n := &pyNode{kind: "Starred", line: t.line, value: value}
		return n.add(value)
	}
	return p.binary(0)
}

// targetList reads what a for assigns to. `in` stops it, since it stops at bitwise_or.
func (p *pyParser) targetList() *pyNode {
	t := p.tok()
	first := p.starTarget()
	if !p.op(",") {
		p.assignTo(first)
		return first
	}
	elts := []*pyNode{first}
	for p.eatOp(",") {
		if p.word("in") {
			break
		}
		elts = append(elts, p.starTarget())
	}
	n := (&pyNode{kind: "Tuple", line: t.line, elts: elts}).add(elts...)
	p.assignTo(n)
	return n
}

// ---------- reading expressions ----------

func (p *pyParser) starExpressions() *pyNode {
	t := p.tok()
	first := p.starExpression()
	if !p.op(",") {
		return first
	}
	elts := []*pyNode{first}
	for p.eatOp(",") {
		if !p.startsExpression() {
			break
		}
		elts = append(elts, p.starExpression())
	}
	return (&pyNode{kind: "Tuple", line: t.line, elts: elts}).add(elts...)
}

// startsExpression says the next token can begin one (a list after a comma may end).
func (p *pyParser) startsExpression() bool {
	t := p.tok()
	switch t.kind {
	case pyTokNumber, pyTokString, pyTokFStart:
		return true
	case pyTokName:
		switch t.text {
		case "True", "False", "None", "not", "lambda", "await":
			return true
		}
		return !pyKeywords[t.text]
	case pyTokOp:
		switch t.text {
		case "(", "[", "{", "-", "+", "~", "...", "*":
			return true
		}
	}
	return false
}

func (p *pyParser) starExpression() *pyNode {
	if t := p.tok(); t.isOp("*") {
		p.at++
		value := p.binary(0)
		n := &pyNode{kind: "Starred", line: t.line, value: value}
		return n.add(value)
	}
	return p.expression()
}

func (p *pyParser) starNamedExpression() *pyNode {
	if p.op("*") {
		return p.starExpression()
	}
	return p.namedExpression()
}

func (p *pyParser) namedExpression() *pyNode {
	t := p.tok()
	if t.isIdent() && p.look(1).isOp(":=") {
		return p.walrus()
	}
	start := p.at
	e := p.expression()
	if p.op(":=") {
		if p.second {
			at := p.at
			p.at++
			if p.try(func() { p.expression() }) {
				p.say(e.line, "cannot use assignment expressions with %s", pyExprName(e))
			}
			p.at = at
		}
		p.fail()
	}
	if p.second && p.op("=") {
		if t.isIdent() && p.at == start+1 {
			if p.followedByValue() {
				p.say(e.line, "invalid syntax. Maybe you meant '==' or ':=' instead of '='?")
			}
		} else if pyBitwiseLevel(e) && !p.startsDisplay(start) && p.followedByValue() {
			p.say(e.line, "cannot assign to %s here. Maybe you meant '==' instead of '='?", pyExprName(e))
		}
	}
	return e
}

// startsDisplay is the guard on that rule: not for what starts as a list, a tuple, a
// generator, True, False or None.
func (p *pyParser) startsDisplay(start int) bool {
	t := &p.toks[start]
	if t.isWord("True") || t.isWord("False") || t.isWord("None") {
		return true
	}
	if !t.isOp("(") && !t.isOp("[") {
		return false
	}
	at := p.at
	defer func() { p.at = at }()
	p.at = start
	var n *pyNode
	if !p.try(func() { p.withoutChecks(func() { n = p.atom() }) }) {
		return false
	}
	return n.kind == "List" || n.kind == "Tuple" || n.kind == "GeneratorExp"
}

func (p *pyParser) walrus() *pyNode {
	t := p.next()
	p.at++ // the :=
	target := &pyNode{kind: "Name", line: t.line, name: t.text, store: true}
	value := p.expression()
	n := &pyNode{kind: "NamedExpr", line: t.line, value: value}
	return n.add(target, value)
}

func (p *pyParser) yieldExpression() *pyNode {
	t := p.next()
	if p.eatWord("from") {
		value := p.expression()
		n := &pyNode{kind: "YieldFrom", line: t.line, value: value}
		return n.add(value)
	}
	n := &pyNode{kind: "Yield", line: t.line}
	if p.startsExpression() {
		n.value = p.starExpressions()
		n.add(n.value)
	}
	return n
}

func (p *pyParser) expression() *pyNode {
	t := p.tok()
	if t.isWord("lambda") {
		return p.lambda()
	}
	start := p.at
	a := p.disjunction()
	if p.second {
		p.forgotComma(start, a)
	}
	if p.word("if") {
		at := p.at
		p.at++
		if b := p.operand(p.disjunction); b != nil {
			if p.eatWord("else") {
				p.deeper(t.line)
				c := p.operand(p.expression)
				p.depth--
				if c != nil {
					n := &pyNode{kind: "IfExp", line: t.line}
					return n.add(b, a, c)
				}
			} else if p.second && !p.op(":") {
				p.say(a.line, "expected 'else' after 'if' expression")
			}
			if !p.peg {
				p.fail()
			}
		}
		p.at = at
	}
	if p.second {
		p.legacyStatement(start, t)
	}
	return a
}

// operand reads what follows an operator, or gives nil. CPython's parser, being PEG,
// just doesn't take an operator it can't read past. That only shows in which words a
// syntax error gets, so the first pass doesn't bother.
func (p *pyParser) operand(read func() *pyNode) *pyNode {
	if !p.peg {
		return read()
	}
	var n *pyNode
	if p.try(func() { n = read() }) {
		return n
	}
	return nil
}

// legacyStatement is CPython's invalid_legacy_expression: print x, with no brackets.
// It reads what follows any name that way, with the checks on.
func (p *pyParser) legacyStatement(start int, t *pyToken) {
	if !t.isIdent() {
		return
	}
	at := p.at
	defer func() { p.at = at }()
	p.at = start + 1
	if p.op("(") || !p.startsExpression() {
		return
	}
	if p.try(func() { p.starExpressions() }) && (t.text == "print" || t.text == "exec") {
		p.say(t.line, "Missing parentheses in call to '%s'. Did you mean %s(...)?", t.text, t.text)
	}
}

// forgotComma is CPython's invalid_expression: two expressions side by side in brackets.
func (p *pyParser) forgotComma(start int, a *pyNode) {
	first := &p.toks[start]
	if first.isIdent() && p.toks[start+1].kind == pyTokString {
		return
	}
	if t := first.text; first.kind == pyTokName && (t == "match" || t == "case" || t == "type" || t == "_") {
		return
	}
	if a.kind == "Name" && (a.name == "print" || a.name == "exec") {
		return
	}
	if !p.startsExpression() || p.op("*") {
		return
	}
	at := p.at
	if p.try(func() { p.withoutChecks(func() { p.expression() }) }) {
		level := p.toks[p.at-1].level
		p.at = at
		if level != 0 {
			p.say(a.line, "invalid syntax. Perhaps you forgot a comma?")
		}
	}
}

// withoutChecks is CPython's expression_without_invalid.
func (p *pyParser) withoutChecks(f func()) {
	saved := p.second
	p.second = false
	defer func() { p.second = saved }()
	f()
}

func (p *pyParser) lambda() *pyNode {
	t := p.next()
	params := p.parameters(":")
	p.wantOp(":")
	if p.tok().kind == pyTokFMiddle {
		p.say(t.line, "f-string: lambda expressions are not allowed without parentheses")
	}
	p.deeper(t.line)
	body := p.expression()
	p.depth--
	n := &pyNode{kind: "Lambda", line: t.line}
	return n.add(params, body)
}

func (p *pyParser) disjunction() *pyNode { return p.boolOp("or", "Or", p.conjunction) }

func (p *pyParser) conjunction() *pyNode { return p.boolOp("and", "And", p.inversion) }

func (p *pyParser) boolOp(word, op string, next func() *pyNode) *pyNode {
	t := p.tok()
	first := next()
	if !p.word(word) {
		return first
	}
	elts := []*pyNode{first}
	for p.word(word) {
		at := p.at
		p.at++
		e := p.operand(next)
		if e == nil {
			p.at = at
			break
		}
		elts = append(elts, e)
	}
	if len(elts) == 1 {
		return first
	}
	return (&pyNode{kind: "BoolOp", line: t.line, op: op, elts: elts}).add(elts...)
}

func (p *pyParser) inversion() *pyNode {
	t := p.tok()
	if !t.isWord("not") {
		return p.comparison()
	}
	p.at++
	p.deeper(t.line)
	value := p.inversion()
	p.depth--
	n := &pyNode{kind: "UnaryOp", line: t.line, op: "Not", value: value}
	return n.add(value)
}

func (p *pyParser) compareOp() string {
	t := p.tok()
	if t.kind == pyTokOp {
		op := map[string]string{"==": "Eq", "!=": "NotEq", "<": "Lt", "<=": "LtE", ">": "Gt", ">=": "GtE"}[t.text]
		if op != "" {
			p.at++
		}
		return op
	}
	switch {
	case t.isWord("in"):
		p.at++
		return "In"
	case t.isWord("not") && p.look(1).isWord("in"):
		p.at += 2
		return "NotIn"
	case t.isWord("is"):
		p.at++
		if p.eatWord("not") {
			return "IsNot"
		}
		return "Is"
	}
	return ""
}

func (p *pyParser) comparison() *pyNode {
	t := p.tok()
	left := p.binary(0)
	var ops []string
	var rights []*pyNode
	for {
		at := p.at
		op := p.compareOp()
		if op == "" {
			break
		}
		right := p.operand(func() *pyNode { return p.binary(0) })
		if right == nil {
			p.at = at
			break
		}
		ops, rights = append(ops, op), append(rights, right)
	}
	if ops == nil {
		return left
	}
	n := &pyNode{kind: "Compare", line: t.line, left: left, ops: ops, elts: rights}
	return n.add(left).add(rights...)
}

// The binary operators, loosest first, all left to right.
var pyBinary = [][]string{{"|"}, {"^"}, {"&"}, {"<<", ">>"}, {"+", "-"}, {"*", "/", "//", "%", "@"}}

func (p *pyParser) binary(level int) *pyNode {
	if level == len(pyBinary) {
		return p.factor()
	}
	t := p.tok()
	depth := p.depth
	defer func() { p.depth = depth }() // a chain is a tree as deep as it's long
	left := p.binary(level + 1)
	for {
		u := p.tok()
		matched := false
		if u.kind == pyTokOp {
			for _, op := range pyBinary[level] {
				matched = matched || u.text == op
			}
		}
		if !matched {
			return left
		}
		at := p.at
		p.at++
		p.deeper(u.line)
		if u.text != "|" && u.text != "^" && u.text != "&" && u.text != "<<" && u.text != ">>" {
			p.notAfterOperator()
		}
		right := p.operand(func() *pyNode { return p.binary(level + 1) })
		if right == nil {
			p.at = at
			return left
		}
		op := "Other"
		if u.text == "+" {
			op = "Add"
		} else if u.text == "-" {
			op = "Sub"
		}
		n := &pyNode{kind: "BinOp", line: t.line, op: op, left: left, right: right}
		left = n.add(left, right)
	}
}

func (p *pyParser) factor() *pyNode {
	t := p.tok()
	if t.isOp("+") || t.isOp("-") || t.isOp("~") {
		p.at++
		p.notAfterOperator()
		p.deeper(t.line)
		value := p.factor()
		p.depth--
		op := map[string]string{"+": "UAdd", "-": "USub", "~": "Invert"}[t.text]
		n := &pyNode{kind: "UnaryOp", line: t.line, op: op, value: value}
		return n.add(value)
	}
	left := p.awaitPrimary()
	if !p.op("**") {
		return left
	}
	at := p.at
	p.at++
	p.deeper(t.line)
	right := p.operand(p.factor)
	p.depth--
	if right == nil {
		p.at = at
		return left
	}
	n := &pyNode{kind: "BinOp", line: t.line, op: "Other", left: left, right: right}
	return n.add(left, right)
}

// notAfterOperator is CPython's invalid_arithmetic and invalid_factor.
func (p *pyParser) notAfterOperator() {
	if t := p.tok(); p.second && t.isWord("not") {
		at := p.at
		if p.try(func() { p.inversion() }) {
			p.say(t.line, "'not' after an operator must be parenthesized")
		}
		p.at = at
	}
}

func (p *pyParser) awaitPrimary() *pyNode {
	t := p.tok()
	if !t.isWord("await") {
		return p.primary()
	}
	p.at++
	value := p.primary()
	n := &pyNode{kind: "Await", line: t.line, value: value}
	return n.add(value)
}

func (p *pyParser) primary() *pyNode {
	line := p.tok().line
	depth := p.depth
	defer func() { p.depth = depth }() // a chain is a tree as deep as it's long
	e := p.atom()
	for {
		t := p.tok()
		if !t.isOp(".") && !t.isOp("(") && !t.isOp("[") {
			return e
		}
		at := p.at
		p.deeper(t.line)
		next := p.operand(func() *pyNode {
			p.at++
			switch t.text {
			case ".":
				attr := p.ident()
				n := &pyNode{kind: "Attribute", line: line, name: attr, value: e}
				return n.add(e)
			case "(":
				n := &pyNode{kind: "Call", line: line, fn: e}
				p.callArguments(n)
				return n.add(e).add(n.args...).add(n.keywords...)
			}
			slice := p.slices()
			p.wantOp("]")
			n := &pyNode{kind: "Subscript", line: line, value: e, slice: slice}
			return n.add(e, slice)
		})
		if next == nil {
			p.at = at
			return e
		}
		e = next
	}
}

// callArguments reads a call's arguments, up to and past the closing bracket, into
// n's args and keywords.
func (p *pyParser) callArguments(n *pyNode) {
	open := p.toks[p.at-1].line
	keyword, unpacked := false, false
	var positionalAfter bool
	for !p.op(")") {
		t := p.tok()
		switch {
		case t.isOp("*"):
			p.at++
			value := p.operand(p.expression)
			if value == nil {
				p.sayLast("Invalid star expression")
				p.fail()
			}
			if p.op("=") {
				at := p.at
				p.at++
				if p.operand(p.expression) != nil {
					p.say(t.line, "cannot assign to iterable argument unpacking")
				}
				p.at = at
			}
			star := (&pyNode{kind: "Starred", line: t.line, value: value}).add(value)
			if unpacked {
				p.say(t.line, "iterable argument unpacking follows keyword argument unpacking")
			}
			n.args = append(n.args, star)
		case t.isOp("**"):
			p.at++
			value := p.expression()
			n.keywords = append(n.keywords, (&pyNode{kind: "keyword", line: t.line, value: value}).add(value))
			keyword, unpacked = true, true
		case (t.isWord("True") || t.isWord("False") || t.isWord("None")) && p.look(1).isOp("="):
			p.say(t.line, "cannot assign to %s", t.text)
		case t.isIdent() && p.look(1).isOp("="):
			p.at += 2
			if u := p.tok(); u.isOp(",") || u.isOp(")") {
				p.say(t.line, "expected argument value expression")
			}
			value := p.expression()
			if p.second && (p.word("for") || p.word("async")) {
				at := p.at
				if p.try(func() { p.comprehension() }) {
					p.say(t.line, "invalid syntax. Maybe you meant '==' or ':=' instead of '='?")
				}
				p.at = at
			}
			n.keywords = append(n.keywords, (&pyNode{kind: "keyword", line: t.line, name: t.text, value: value}).add(value))
			keyword = true
		default:
			var e *pyNode
			if t.isIdent() && p.look(1).isOp(":=") {
				e = p.walrus()
			} else {
				e = p.expression()
				if p.op(":=") {
					p.fail()
				}
			}
			if p.op("=") {
				p.say(e.line, "expression cannot contain assignment, perhaps you meant \"==\"?")
			}
			if (p.word("for") || p.word("async")) && n.kind == "Call" {
				generators := p.comprehension()
				if len(n.args)+len(n.keywords) > 0 || p.op(",") {
					p.say(e.line, "Generator expression must be parenthesized")
				}
				e = (&pyNode{kind: "GeneratorExp", line: open}).add(e).add(generators...)
			}
			if keyword {
				positionalAfter = true
				if !p.second {
					p.fail()
				}
			}
			n.args = append(n.args, e)
		}
		if !p.eatOp(",") || (positionalAfter && !p.startsExpression() && !p.op("**")) {
			break
		}
	}
	if positionalAfter {
		if unpacked {
			p.sayLast("positional argument follows keyword argument unpacking")
		}
		p.sayLast("positional argument follows keyword argument")
	}
	p.wantOp(")")
}

func (p *pyParser) slices() *pyNode {
	t := p.tok()
	first := p.sliceItem()
	if !p.op(",") && first.kind != "Starred" {
		return first
	}
	elts := []*pyNode{first}
	for p.eatOp(",") {
		if p.op("]") {
			break
		}
		elts = append(elts, p.sliceItem())
	}
	return (&pyNode{kind: "Tuple", line: t.line, elts: elts}).add(elts...)
}

func (p *pyParser) sliceItem() *pyNode {
	t := p.tok()
	if t.isOp("*") {
		p.at++
		value := p.expression()
		return (&pyNode{kind: "Starred", line: t.line, value: value}).add(value)
	}
	n := &pyNode{kind: "Slice", line: t.line}
	if !p.op(":") {
		e := p.namedExpression()
		if !p.op(":") {
			return e
		}
		n.add(e)
	}
	p.wantOp(":")
	if !p.op(":") && !p.op("]") && !p.op(",") {
		n.add(p.expression())
	}
	if p.eatOp(":") && !p.op("]") && !p.op(",") {
		n.add(p.expression())
	}
	return n
}

func (p *pyParser) atom() *pyNode {
	t := p.tok()
	switch t.kind {
	case pyTokName:
		switch t.text {
		case "True", "False", "None":
			p.at++
			return &pyNode{kind: "Constant", line: t.line, constant: t.text}
		}
		if pyKeywords[t.text] {
			p.fail()
		}
		p.at++
		return &pyNode{kind: "Name", line: t.line, name: t.text}
	case pyTokNumber:
		p.at++
		return &pyNode{kind: "Constant", line: t.line, constant: pyNumberKind(t.text)}
	case pyTokString, pyTokFStart:
		return p.strings()
	case pyTokOp:
		switch t.text {
		case "(":
			return p.group()
		case "[":
			return p.listDisplay()
		case "{":
			return p.braces()
		case "...":
			p.at++
			return &pyNode{kind: "Constant", line: t.line, constant: "Ellipsis"}
		}
	}
	p.fail()
	return nil
}

func pyNumberKind(s string) string {
	s = strings.ToLower(s)
	if strings.HasSuffix(s, "j") {
		return "complex"
	}
	if strings.HasPrefix(s, "0x") || strings.HasPrefix(s, "0o") || strings.HasPrefix(s, "0b") {
		return "int"
	}
	if strings.ContainsAny(s, ".e") {
		return "float"
	}
	return "int"
}

func (p *pyParser) group() *pyNode {
	t := p.next()
	if p.eatOp(")") {
		return &pyNode{kind: "Tuple", line: t.line, paren: true}
	}
	if p.word("yield") {
		e := p.yieldExpression()
		p.wantOp(")")
		e.paren = true
		return e
	}
	if p.op("**") {
		p.sayLast("cannot use double starred expression here")
		p.fail()
	}
	first := p.starNamedExpression()
	if p.word("for") || p.word("async") {
		if first.kind == "Starred" {
			p.say(first.line, "iterable unpacking cannot be used in comprehension")
		}
		generators := p.comprehension()
		p.wantOp(")")
		n := &pyNode{kind: "GeneratorExp", line: t.line, paren: true}
		return n.add(first).add(generators...)
	}
	if p.op(")") {
		if first.kind == "Starred" {
			p.say(first.line, "cannot use starred expression here")
		}
		p.at++
		first.paren = true
		return first
	}
	if !p.op(",") {
		p.fail()
	}
	elts := []*pyNode{first}
	for p.eatOp(",") {
		if p.op(")") {
			break
		}
		elts = append(elts, p.starNamedExpression())
	}
	p.wantOp(")")
	return (&pyNode{kind: "Tuple", line: t.line, elts: elts, paren: true}).add(elts...)
}

func (p *pyParser) listDisplay() *pyNode {
	t := p.next()
	if p.eatOp("]") {
		return &pyNode{kind: "List", line: t.line}
	}
	first := p.starNamedExpression()
	if p.word("for") || p.word("async") {
		if first.kind == "Starred" {
			p.say(first.line, "iterable unpacking cannot be used in comprehension")
		}
		generators := p.comprehension()
		p.wantOp("]")
		return (&pyNode{kind: "ListComp", line: t.line}).add(first).add(generators...)
	}
	elts := []*pyNode{first}
	for p.eatOp(",") {
		if p.op("]") {
			break
		}
		elts = append(elts, p.starNamedExpression())
	}
	p.forgotBrackets(first)
	p.wantOp("]")
	return (&pyNode{kind: "List", line: t.line, elts: elts}).add(elts...)
}

// forgotBrackets is a comprehension over a tuple written without its brackets.
func (p *pyParser) forgotBrackets(first *pyNode) {
	if p.second && (p.word("for") || p.word("async")) {
		at := p.at
		if p.try(func() { p.comprehension() }) {
			p.say(first.line, "did you forget parentheses around the comprehension target?")
		}
		p.at = at
	}
}

func (p *pyParser) braces() *pyNode {
	t := p.next()
	if p.eatOp("}") {
		return &pyNode{kind: "Dict", line: t.line}
	}
	if p.op("**") {
		return p.dictFrom(t, nil, nil)
	}
	first := p.starNamedExpression()
	if p.op(":") && first.kind != "Starred" && (first.kind != "NamedExpr" || first.paren) {
		value := p.dictValue()
		if p.word("for") || p.word("async") {
			generators := p.comprehension()
			p.wantOp("}")
			return (&pyNode{kind: "DictComp", line: t.line}).add(first, value).add(generators...)
		}
		return p.dictFrom(t, first, value)
	}
	if p.word("for") || p.word("async") {
		if first.kind == "Starred" {
			p.say(first.line, "iterable unpacking cannot be used in comprehension")
		}
		generators := p.comprehension()
		p.wantOp("}")
		return (&pyNode{kind: "SetComp", line: t.line}).add(first).add(generators...)
	}
	elts := []*pyNode{first}
	for p.eatOp(",") {
		if p.op("}") {
			break
		}
		elts = append(elts, p.starNamedExpression())
	}
	p.forgotBrackets(first)
	p.wantOp("}")
	return (&pyNode{kind: "Set", line: t.line, elts: elts}).add(elts...)
}

// dictValue reads the : and value of a dict entry.
func (p *pyParser) dictValue() *pyNode {
	t := p.next()
	if u := p.tok(); u.isOp("}") || u.isOp(",") {
		p.say(t.line, "expression expected after dictionary key and ':'")
	} else if u.isOp("*") {
		p.say(u.line, "cannot use a starred expression in a dictionary value")
	}
	return p.expression()
}

func (p *pyParser) dictFrom(t *pyToken, key, value *pyNode) *pyNode {
	n := &pyNode{kind: "Dict", line: t.line}
	var values []*pyNode
	if key != nil {
		n.keys, values = append(n.keys, key), append(values, value)
		if !p.eatOp(",") {
			p.wantOp("}")
			return n.add(n.keys...).add(values...)
		}
	}
	for !p.op("}") {
		if u := p.tok(); u.isOp("**") {
			p.at++
			if p.word("for") || p.word("async") {
				p.fail()
			}
			value := p.binary(0)
			if key == nil && len(n.keys) == 0 && (p.word("for") || p.word("async")) {
				p.say(u.line, "dict unpacking cannot be used in dict comprehension")
			}
			n.keys, values = append(n.keys, nil), append(values, value)
		} else {
			start := p.at
			var k, v *pyNode
			if !p.try(func() {
				k = p.expression()
				if !p.op(":") {
					p.fail()
				}
				v = p.dictValue()
			}) {
				p.at = start
				p.badDictEntry()
				p.fail()
			}
			n.keys, values = append(n.keys, k), append(values, v)
		}
		if !p.eatOp(",") {
			break
		}
	}
	p.wantOp("}")
	return n.add(n.keys...).add(values...)
}

// badDictEntry is CPython's invalid_kvpair, for an entry after the first. It's in an
// alternative of the dict rule that the first pass runs too, so it says so right away.
func (p *pyParser) badDictEntry() {
	saved := p.peg
	p.peg = true
	defer func() { p.peg = saved }()
	var a *pyNode
	if !p.try(func() { a = p.expression() }) {
		return
	}
	if !p.op(":") {
		panic(&pySyntaxError{a.line, "':' expected after dictionary key"})
	}
	colon := p.next()
	if u := p.tok(); u.isOp("}") || u.isOp(",") {
		panic(&pySyntaxError{colon.line, "expression expected after dictionary key and ':'"})
	} else if u.isOp("*") {
		p.at++
		if p.try(func() { p.binary(0) }) {
			panic(&pySyntaxError{u.line, "cannot use a starred expression in a dictionary value"})
		}
	}
}

func (p *pyParser) comprehension() []*pyNode {
	var out []*pyNode
	for {
		t := p.tok()
		if t.isWord("async") {
			p.at++
		}
		if !p.word("for") {
			if t.isWord("async") {
				p.fail()
			}
			return out
		}
		p.at++
		n := &pyNode{kind: "comprehension"}
		at := p.at
		target := p.forTarget()
		if target == nil {
			if p.second {
				p.at = at
				p.badComprehensionTarget()
			}
			p.fail()
		}
		n.add(target, p.disjunction())
		for p.eatWord("if") {
			n.add(p.disjunction())
		}
		out = append(out, n)
	}
}

// badComprehensionTarget is CPython's invalid_for_if_clause, then invalid_for_target.
func (p *pyParser) badComprehensionTarget() {
	at := p.at
	if p.try(func() {
		p.binary(0)
		for p.eatOp(",") {
			if !p.startsExpression() {
				break
			}
			p.binary(0)
		}
	}) && !p.word("in") {
		p.sayLast("'in' expected after for-loop variables")
	}
	p.at = at
	p.badForTarget()
}

// strings reads one or more adjacent string literals as one constant, or an f-string.
func (p *pyParser) strings() *pyNode {
	line := p.tok().line
	n := &pyNode{kind: "Constant", line: line, constant: "str"}
	var text strings.Builder
	bytes, plain, fstring := false, false, false
	var problem string
	for {
		t := p.tok()
		if t.kind == pyTokFStart {
			fstring, n.kind = true, "JoinedStr"
			n.add(p.fstring()...)
			continue
		}
		if t.kind != pyTokString {
			break
		}
		p.at++
		s, isBytes, why := pyDecodeString(t.text)
		bytes, plain = bytes || isBytes, plain || !isBytes
		text.WriteString(s)
		if problem == "" {
			problem = why
		}
	}
	p.tok() // CPython has looked past the last string by the time it says anything
	if bytes && (plain || fstring) {
		panic(&pySyntaxError{p.toks[p.far].line, "cannot mix bytes and nonbytes literals"})
	}
	if problem != "" {
		panic(&pySyntaxError{p.toks[p.far].line, problem})
	}
	if bytes {
		n.constant = "bytes"
	}
	n.str = text.String()
	return n
}

// fstring reads one f-string's parts: the fields' expressions are real ones.
func (p *pyParser) fstring() []*pyNode {
	p.at++
	var out []*pyNode
	raw := strings.ContainsAny(strings.ToLower(p.toks[p.at-1].text), "r")
	for {
		t := p.tok()
		switch {
		case t.kind == pyTokFEnd:
			p.at++
			return out
		case t.kind == pyTokFMiddle:
			p.at++
			if !raw {
				if _, why := pyDecodeBody(t.text, false); why != "" {
					panic(&pySyntaxError{t.line, why})
				}
			}
		case t.isOp("{"):
			out = append(out, p.replacementField())
		default:
			p.fail()
		}
	}
}

func (p *pyParser) replacementField() *pyNode {
	open := p.next()
	if u := p.tok(); u.isOp("=") || u.isOp("!") || u.isOp(":") || u.isOp("}") {
		p.say(u.line, "f-string: valid expression required before '%s'", u.text)
	}
	if p.second {
		at := p.at
		if !p.try(func() { p.rightSide() }) {
			p.at = at
			p.say(open.line, "f-string: expecting a valid expression after '{'")
		}
		p.at = at
	}
	value := p.rightSide()
	n := &pyNode{kind: "FormattedValue", line: open.line, value: value}
	n.add(value)
	debug := p.eatOp("=")
	conversion := ""
	if u := p.tok(); p.second && !u.isOp("!") && !u.isOp(":") && !u.isOp("}") {
		if debug {
			p.say(u.line, "f-string: expecting '!', or ':', or '}'")
		}
		p.say(u.line, "f-string: expecting '=', or '!', or ':', or '}'")
	}
	if p.op("!") {
		bang := p.next()
		u := p.tok()
		if p.second && (u.isOp(":") || u.isOp("}")) {
			p.say(u.line, "f-string: missing conversion character")
		}
		if u.kind != pyTokName {
			p.say(u.line, "f-string: invalid conversion character")
			p.fail()
		}
		p.at++
		if u.at != bang.at+1 {
			panic(&pySyntaxError{bang.line, "f-string: conversion type must come right after the exclamation mark"})
		}
		conversion = u.text
		if v := p.tok(); p.second && !v.isOp(":") && !v.isOp("}") {
			p.say(v.line, "f-string: expecting ':' or '}'")
		}
	}
	if colon := p.tok(); p.eatOp(":") {
		spec := &pyNode{kind: "JoinedStr", line: colon.line}
		for {
			t := p.tok()
			if t.kind == pyTokFMiddle {
				p.at++
			} else if t.isOp("{") {
				spec.add(p.replacementField())
			} else {
				break
			}
		}
		n.add(spec)
		if !p.op("}") {
			p.say(p.tok().line, "f-string: expecting '}', or format specs")
		}
	}
	if !p.op("}") {
		p.say(p.tok().line, "f-string: expecting '}'")
		p.fail()
	}
	p.at++
	if conversion != "" && conversion != "s" && conversion != "r" && conversion != "a" {
		panic(&pySyntaxError{open.line, "f-string: invalid conversion character " + pyRepr(conversion) + ": expected 's', 'r', or 'a'"})
	}
	return n
}

// ---------- string values ----------

// pyDecodeString gives a string token's value, whether it's bytes, and what Python
// would say is wrong with it. A \N{...} escape stays as written: the app has no table
// of Unicode names.
func pyDecodeString(tok string) (value string, isBytes bool, problem string) {
	i := strings.IndexAny(tok, `"'`)
	prefix := strings.ToLower(tok[:i])
	body := tok[i:]
	quote := 1
	if len(body) >= 6 && (strings.HasPrefix(body, `"""`) || strings.HasPrefix(body, `'''`)) {
		quote = 3
	}
	body = body[quote : len(body)-quote]
	isBytes = strings.Contains(prefix, "b")
	raw := strings.Contains(prefix, "r")
	if isBytes {
		for i := 0; i < len(body); i++ {
			if body[i] >= 0x80 {
				return "", true, "bytes can only contain ASCII literal characters"
			}
		}
	}
	if raw {
		return body, isBytes, ""
	}
	if !strings.Contains(body, `\`) {
		return body, isBytes, ""
	}
	value, problem = pyDecodeBody(body, isBytes)
	return value, isBytes, problem
}

// pyDecodeBody turns a string's escapes into what they mean. The numbers in Python's
// message count each non-ASCII character as ten bytes, since it writes those as \U
// escapes before decoding.
func pyDecodeBody(body string, isBytes bool) (value, problem string) {
	var b strings.Builder
	pos := 0 // the position Python's decoder would be at
	for i := 0; i < len(body); {
		c := body[i]
		if c != '\\' {
			if c < 0x80 {
				b.WriteByte(c)
				i++
				pos++
				continue
			}
			r, size := utf8.DecodeRuneInString(body[i:])
			b.WriteRune(r)
			i += size
			pos += 10
			continue
		}
		start := pos
		if i+1 >= len(body) {
			b.WriteByte(c)
			break
		}
		e := body[i+1]
		single := map[byte]string{'\n': "", '\\': `\`, '\'': "'", '"': `"`, 'a': "\a", 'b': "\b", 'f': "\f", 'n': "\n", 'r': "\r", 't': "\t", 'v': "\v"}
		if s, ok := single[e]; ok {
			b.WriteString(s)
			i += 2
			pos += 2
			continue
		}
		switch {
		case e >= '0' && e <= '7':
			v, j := 0, i+1
			for j < len(body) && j < i+4 && body[j] >= '0' && body[j] <= '7' {
				v = v*8 + int(body[j]-'0')
				j++
			}
			pyWriteCode(&b, rune(v), isBytes)
			pos += j - i
			i = j
			continue
		case e == 'x' || (!isBytes && (e == 'u' || e == 'U')):
			size := map[byte]int{'x': 2, 'u': 4, 'U': 8}[e]
			v, j := 0, i+2
			for j < len(body) && j < i+2+size && pyHexDigit(int(body[j])) {
				v = v*16 + hexValue(body[j])
				j++
			}
			if j != i+2+size {
				if isBytes {
					return "", fmt.Sprintf("(value error) invalid \\x escape at position %d", start)
				}
				name := map[byte]string{'x': `\xXX`, 'u': `\uXXXX`, 'U': `\UXXXXXXXX`}[e]
				return "", fmt.Sprintf("(unicode error) 'unicodeescape' codec can't decode bytes in position %d-%d: truncated %s escape", start, start+j-i-1, name)
			}
			if v > unicode.MaxRune {
				return "", fmt.Sprintf("(unicode error) 'unicodeescape' codec can't decode bytes in position %d-%d: illegal Unicode character", start, start+j-i-1)
			}
			pyWriteCode(&b, rune(v), isBytes)
			pos += j - i
			i = j
			continue
		case e == 'N' && !isBytes:
			if i+2 < len(body) && body[i+2] == '{' {
				if end := strings.IndexByte(body[i+3:], '}'); end > 0 {
					b.WriteString(body[i : i+3+end+1])
					pos += 3 + end + 1
					i += 3 + end + 1
					continue
				}
				end := min(len(body), i+3)
				return "", fmt.Sprintf("(unicode error) 'unicodeescape' codec can't decode bytes in position %d-%d: malformed \\N character escape", start, start+end-i-1)
			}
			return "", fmt.Sprintf("(unicode error) 'unicodeescape' codec can't decode bytes in position %d-%d: malformed \\N character escape", start, start+1)
		}
		// An escape that means nothing keeps its backslash.
		b.WriteByte(c)
		i++
		pos++
	}
	return b.String(), ""
}

func hexValue(c byte) int {
	switch {
	case c >= 'a':
		return int(c-'a') + 10
	case c >= 'A':
		return int(c-'A') + 10
	}
	return int(c - '0')
}

func pyWriteCode(b *strings.Builder, r rune, isBytes bool) {
	switch {
	case isBytes:
		b.WriteByte(byte(r))
	case r >= 0xd800 && r <= 0xdfff: // a lone surrogate, which Python's str can hold
		b.Write([]byte{0xe0 | byte(r>>12), 0x80 | byte(r>>6)&0x3f, 0x80 | byte(r)&0x3f})
	default:
		b.WriteRune(r)
	}
}

// pyRepr is repr() of a str.
func pyRepr(s string) string {
	quote := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == rune(quote) || r == '\\':
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r < 0x7f || pyPrintable(r):
			b.WriteRune(r)
		case r <= 0xff:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r <= 0xffff:
			fmt.Fprintf(&b, `\u%04x`, r)
		default:
			fmt.Fprintf(&b, `\U%08x`, r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}
