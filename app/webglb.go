package main

// Web GLBs. A page that loads an attached OBJ, FBX, STL or PLY as it is downloads all
// of it (the Raka machines' OBJs are 13 to 108 MB each, 335 MB in all), so Chimera has
// Blender save each one beside it as "<its name>-web.glb": one file a page loads with
// three.js's GLTFLoader, its meshes Draco-compressed and its textures inside (WebP where
// the Blender has it), the 10MSP's 15 MB OBJ a 1 MB GLB and the KX033's 82 MB a 2.7 MB
// one. An OBJ's, STL's or PLY's parts come out upright in their data, with no turn or
// place of their own, the same names, so the parts listed for it are the ones to move.
// It's turntable.py's export mode, in the same sandbox (turnRun), and like a turntable
// it isn't made again from the same bytes (".<its name>.json" beside it says what it
// was made from). On by default, with a switch on the composer (the user's yes, Nov 9).

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"
)

const (
	webVersion   = 1
	webTimeout   = 10 * time.Minute
	webFileMax   = 1 << 30
	webMaxModels = 24 // a message's models saved as GLBs; the rest are named in the reply's note
)

// webable says whether Chimera saves a model as a GLB for pages: an OBJ, FBX, STL or PLY
// (a glTF is one already).
func webable(f AttachedFile) bool {
	if f.Kind != "3d" || f.Made != "" {
		return false
	}
	switch strings.ToLower(path.Ext(f.Path)) {
	case ".obj", ".fbx", ".stl", ".ply":
		return true
	}
	return false
}

// webMade is the record beside a web GLB: what it was made from.
type webMade struct {
	Version int       `json:"version"`
	Model   string    `json:"model"`
	Sum     string    `json:"sum"` // of the model and the files it loads
	Bytes   int64     `json:"bytes"`
	Seconds float64   `json:"seconds"`
	At      time.Time `json:"at"`
}

func webRecord(rel string) string { return path.Join(path.Dir(rel), "."+path.Base(rel)+".json") }

// webGLB saves model (a path in folder) as a GLB for pages beside it, or finds the one
// saved there from the same bytes. It gives the GLB's path in folder, and whether it
// was there already. also names the message's other files (an FBX's textures).
func webGLB(ctx context.Context, blender, cache, folder, model string, also []string) (string, bool, error) {
	if _, err := insideFolder(folder, model); err != nil {
		return "", false, errors.New("it isn't in the chat's folder any more")
	}
	needs := turnNeeds(folder, model, also)
	sum, err := turnSum(folder, append([]string{model}, needs...))
	if err != nil {
		return "", false, err
	}
	rel, old, err := webPath(folder, model)
	if err != nil {
		return "", false, err
	}
	if old != nil && old.Version == webVersion && old.Sum == sum {
		if full, err := insideFolder(folder, rel); err == nil && webFile(full) {
			return rel, true, nil
		}
	}
	start := time.Now()
	opts := map[string]any{"model": "in/" + model, "out": "out", "frames": 0, "px": 0, "samples": 0, "gpu": false, "glb": "out/model.glb"}
	run, err := turnRun(ctx, blender, cache, folder, append([]string{model}, needs...), opts, webTimeout, nil)
	if err != nil {
		return "", false, err
	}
	defer os.RemoveAll(run)
	src := filepath.Join(run, "out", "model.glb")
	if !webFile(src) { // read outside the sandbox: a plain file that is a GLB
		return "", false, errors.New("Blender didn't save a GLB")
	}
	st, _ := os.Stat(src)
	made := webMade{Version: webVersion, Model: model, Sum: sum, Bytes: st.Size(), Seconds: round1(time.Since(start).Seconds()), At: time.Now().UTC()}
	if err := placeWeb(folder, rel, src, made); err != nil {
		return "", false, err
	}
	return rel, false, nil
}

// webPath is where a model's GLB for pages goes: "<its name>-web.glb" beside it, or
// with a number when that name is someone else's file. Chimera's own one for this
// model is used again, and its record comes back.
func webPath(folder, model string) (string, *webMade, error) {
	root, err := filepath.EvalSymlinks(folder)
	if err != nil {
		return "", nil, err
	}
	stem := strings.TrimSuffix(path.Base(model), path.Ext(model))
	for n := 1; n < 100; n++ {
		name := stem + "-web.glb"
		if n > 1 {
			name = fmt.Sprintf("%s-web-%d.glb", stem, n)
		}
		cand := path.Join(path.Dir(model), name)
		st, err := os.Lstat(filepath.Join(root, filepath.FromSlash(cand)))
		if errors.Is(err, os.ErrNotExist) {
			return cand, nil, nil
		}
		if err != nil || !st.Mode().IsRegular() {
			continue
		}
		b, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(webRecord(cand))))
		if err != nil {
			continue // someone else's file
		}
		var m webMade
		if json.Unmarshal(b, &m) == nil && m.Model == model {
			return cand, &m, nil
		}
	}
	return "", nil, errors.New("too many GLBs of that name beside it")
}

// webFile says whether a file is a plain GLB of a sane size.
func webFile(p string) bool {
	st, err := os.Lstat(p)
	if err != nil || !st.Mode().IsRegular() || st.Size() < 20 || st.Size() > webFileMax {
		return false
	}
	return bytes.HasPrefix(readHead(p, 4), []byte("glTF"))
}

// placeWeb moves the GLB into the chat's folder, in place of the one made before, with
// its record beside it.
func placeWeb(folder, rel, src string, made webMade) error {
	root, err := filepath.EvalSymlinks(folder)
	if err != nil {
		return err
	}
	dst := filepath.Join(root, filepath.FromSlash(rel))
	if real, err := filepath.EvalSymlinks(filepath.Dir(dst)); err != nil || (real != root && !strings.HasPrefix(real, root+string(filepath.Separator))) {
		return errors.New("its folder leads out of the chat's folder")
	}
	if st, err := os.Lstat(dst); err == nil && !st.Mode().IsRegular() {
		return fmt.Errorf("%s isn't a plain file", rel)
	}
	_ = os.Remove(dst)
	if err := moveFile(src, dst); err != nil {
		return fmt.Errorf("couldn't put %s in the chat's folder: %v", rel, err)
	}
	b, _ := json.MarshalIndent(made, "", " ")
	return os.WriteFile(filepath.Join(root, filepath.FromSlash(webRecord(rel))), b, 0o644)
}

// webWords says what a web GLB is, for what the model is told: what it was made from,
// how much smaller it is, and to load it rather than the original.
func webWords(from string, size, fromSize int64) string {
	smaller := ""
	if size > 0 && fromSize > size*3/2 {
		smaller = fmt.Sprintf(", %s the size of `%s`", sizeRatio(size, fromSize), path.Base(from))
	}
	return fmt.Sprintf("A copy of `%s` that Chimera saved for web pages%s: the same model and part names, its meshes Draco-compressed and its textures inside, "+
		"every part upright with no turn or place of its own (for an OBJ, STL or PLY). Load this one in a page, not `%s`", from, smaller, path.Base(from))
}

// sizeRatio says how much smaller: "1/15", "half" or "two thirds".
func sizeRatio(size, of int64) string {
	r := float64(of) / float64(size)
	switch {
	case r >= 2.5:
		return fmt.Sprintf("1/%d", int(r+0.5))
	case r >= 1.75:
		return "half"
	}
	return "two thirds"
}
