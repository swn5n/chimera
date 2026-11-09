package main

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"log"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

// fakeTurnBlender is a stand-in for Blender that does what turntable.py does from
// the outside: it reads the options after "--", checks the model and what an OBJ
// names are in the run's folder, writes tiny WebP frames and a poster, and prints
// the progress lines. A model named "slow…" takes a quarter second a frame, and one
// named "broken…" fails the way the script does. Its pid goes in the kernel cache
// (the one other folder the sandbox lets it write), so a test can see it's gone.
func fakeTurnBlender(t *testing.T) string {
	t.Helper()
	py := findPython()
	if py == "" {
		t.Skip("no Python here")
	}
	if !canSandbox() {
		t.Skip("no sandbox here")
	}
	p := filepath.Join(t.TempDir(), "blender")
	code := `#!` + py + ` -I
import json, os, signal, sys, time
args = sys.argv[1:]
opt = json.loads(args[args.index("--") + 1])
def say(*a):
    print("chimera-turn:", *a, flush=True)
model, out, frames, px = opt["model"], opt["out"], int(opt["frames"]), int(opt["px"])
cache = os.environ.get("XDG_CACHE_HOME")
if cache:
    open(os.path.join(cache, "pid"), "w").write(str(os.getpid()))
if not os.path.exists(model):
    say("error", "no model at " + model); sys.exit(3)
name = os.path.basename(model)
if name.startswith("broken"):
    say("error", "Blender couldn't read it: not a model"); sys.exit(3)
if name.startswith("gpucrash") and opt.get("gpu"):
    # dies on the GPU as Cycles' Metal code did under the sandbox, leaving Blender's crash report
    say("info", json.dumps({"faces": 12, "size": [1, 1, 1], "device": "GPU (stand-in)", "format": "webp"}))
    open(os.path.join(os.environ.get("TMPDIR", "."), "blender.crash.txt"), "w").write("# Blender 5.2.2\nccl::MetalKernelPipeline::compile() + 3772\n")
    sys.stdout.flush()
    os.kill(os.getpid(), signal.SIGSEGV)
if name.endswith(".obj"):
    for line in open(model):
        if line.startswith("mtllib "):
            mtl = os.path.join(os.path.dirname(model), line.split(None, 1)[1].strip())
            if not os.path.exists(mtl):
                say("error", "missing " + mtl); sys.exit(3)
            for l2 in open(mtl):
                if l2.startswith("map_Kd "):
                    tex = os.path.join(os.path.dirname(mtl), l2.split(None, 1)[1].strip())
                    if not os.path.exists(tex):
                        say("error", "missing " + tex); sys.exit(3)
os.makedirs(out, exist_ok=True)
say("imported", "0.0")
if opt.get("glb"):
    js = json.dumps({"asset": {"version": "2.0"}, "extensionsUsed": ["KHR_draco_mesh_compression"], "extensionsRequired": ["KHR_draco_mesh_compression"],
                     "scenes": [{"nodes": [0, 1]}], "nodes": [{"name": "Arm", "mesh": 0}, {"name": "Cab", "mesh": 0}],
                     "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
                     "accessors": [{"count": 3, "type": "VEC3", "componentType": 5126, "min": [0, 0, 0], "max": [1, 1, 1]}]}).encode()
    js += b" " * (-len(js) % 4)
    glb = b"glTF" + (2).to_bytes(4, "little") + (20 + len(js)).to_bytes(4, "little") + len(js).to_bytes(4, "little") + b"JSON" + js
    open(opt["glb"], "wb").write(glb)
    say("glb", len(glb), "0.0")
    if frames <= 0:
        say("done", "0.0"); sys.exit(0)
say("info", json.dumps({"faces": 12, "size": [1.5, 2, 3], "device": "GPU (stand-in)" if opt.get("gpu") else "CPU", "format": "webp"}))
def webp(w, h):
    body = b"VP8X" + (10).to_bytes(4, "little") + bytes([0x10, 0, 0, 0]) + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    return b"RIFF" + (4 + len(body)).to_bytes(4, "little") + b"WEBP" + body
pad = max(2, len(str(frames - 1)))
for f in range(frames):
    if name.startswith("slow"):
        time.sleep(0.25)
    open(os.path.join(out, "f%0*d.webp" % (pad, f)), "wb").write(webp(px, px))
    if f == 0:
        open(os.path.join(out, "poster.webp"), "wb").write(webp(px, px))
    say("frame", f, "0.01")
say("done", "0.1")
`
	if err := os.WriteFile(p, []byte(code), 0o755); err != nil {
		t.Fatal(err)
	}
	return p
}

// webpOf is a WebP file's header, enough for its facts: a VP8X chunk with its size.
func webpOf(w, h int, alpha bool) []byte {
	body := []byte("VP8X")
	body = binary.LittleEndian.AppendUint32(body, 10)
	flags := byte(0)
	if alpha {
		flags = 0x10
	}
	body = append(body, flags, 0, 0, 0, byte(w-1), byte((w-1)>>8), byte((w-1)>>16), byte(h-1), byte((h-1)>>8), byte((h-1)>>16))
	out := append([]byte("RIFF"), binary.LittleEndian.AppendUint32(nil, uint32(4+len(body)))...)
	return append(append(out, "WEBP"...), body...)
}

func writeFiles(t *testing.T, root string, files map[string]string) {
	t.Helper()
	for rel, body := range files {
		p := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

func TestATurntableLoadsWhatItsModelNames(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	writeFiles(t, root, map[string]string{
		"m/x.obj":         "mtllib x.mtl\nmtllib two words.mtl\nv 0 0 0\n",
		"m/x.mtl":         "newmtl a\nmap_Kd tex/a.png\nmap_Bump -bm 0.5 bump.png\nmap_Ks gone.png\nmap_Kd C:\\Users\\me\\Desktop\\far.png\n",
		"m/two words.mtl": "newmtl b\nmap_Kd b.png\n",
		"m/tex/a.png":     "A", "m/bump.png": "B", "m/b.png": "C", "m/far.png": "F",
		"g/scene.gltf": `{"buffers":[{"uri":"scene.bin"},{"uri":"data:application/octet-stream;base64,AAAA"}],"images":[{"uri":"textures/a%20b.png"},{"uri":"../m/b.png"},{"uri":"../../etc/passwd"}]}`,
		"g/scene.bin":  "BIN", "g/textures/a b.png": "T",
		"f/rig.fbx": "Kaydara FBX Binary  \x00", "f/rig.png": "R", "f/maps/n.jpg": "N", "other/z.png": "Z",
	})
	os.WriteFile(filepath.Join(outside, "secret.png"), []byte("S"), 0o644)
	os.Symlink(filepath.Join(outside, "secret.png"), filepath.Join(root, "m", "link.png"))
	os.WriteFile(filepath.Join(root, "m", "y.obj"), []byte("mtllib y.mtl\n"), 0o644)
	os.WriteFile(filepath.Join(root, "m", "y.mtl"), []byte("map_Kd link.png\n"), 0o644)

	if got := strings.Join(turnNeeds(root, "m/x.obj", nil), " "); got != "m/b.png m/bump.png m/far.png m/tex/a.png m/two words.mtl m/x.mtl" {
		t.Errorf("OBJ: %q", got)
	}
	// "../m/b.png" stays inside the chat's folder, so it's used; ../../ would leave it.
	if got := strings.Join(turnNeeds(root, "g/scene.gltf", nil), " "); got != "g/scene.bin g/textures/a b.png m/b.png" {
		t.Errorf("glTF: %q", got)
	}
	if got := strings.Join(turnNeeds(root, "f/rig.fbx", []string{"f/rig.fbx", "f/rig.png", "f/maps/n.jpg", "other/z.png"}), " "); got != "f/maps/n.jpg f/rig.png" {
		t.Errorf("FBX: %q", got)
	}
	if got := turnNeeds(root, "m/y.obj", nil); len(got) != 1 || got[0] != "m/y.mtl" {
		t.Errorf("a texture that's a link out of the folder: %q", got)
	}
}

func TestATurntableIsMadeInTheSandboxAndKeptForNextTime(t *testing.T) {
	blender := fakeTurnBlender(t)
	folder, cache := t.TempDir(), t.TempDir()
	writeFiles(t, folder, map[string]string{
		"machines/x.obj":   "mtllib x.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
		"machines/x.mtl":   "newmtl a\nmap_Kd tex.png\n",
		"machines/tex.png": "first",
		// someone's own folder with the name a turntable of y would take
		"machines/y.stl": "solid y\nendsolid y\n", "machines/y-turntable/notes.txt": "mine",
	})
	set := turnSettings{Frames: 8, Px: 64, Samples: 1, Start: 45}
	var seen []turnProgress
	res, err := renderTurntable(context.Background(), blender, cache, folder, "machines/x.obj", nil, set, func(p turnProgress) { seen = append(seen, p) })
	if err != nil {
		t.Fatal(err)
	}
	if res.Dir != "machines/x-turntable" || len(res.Frames) != 8 || res.Frames[7] != "machines/x-turntable/f07.webp" || res.Poster != "machines/x-turntable/poster.webp" || res.Reused {
		t.Fatalf("%+v", res)
	}
	for _, p := range append(res.Frames, res.Poster) {
		if b, err := os.ReadFile(filepath.Join(folder, filepath.FromSlash(p))); err != nil || !bytes.HasPrefix(b, []byte("RIFF")) {
			t.Fatalf("%s isn't in the chat's folder: %v", p, err)
		}
	}
	var rec turnMade
	b, _ := os.ReadFile(filepath.Join(folder, "machines", "x-turntable", turnRecord))
	if json.Unmarshal(b, &rec) != nil || rec.Model != "machines/x.obj" || rec.Faces != 12 || rec.Settings != set || len(rec.Frames) != 8 {
		t.Fatalf("record: %s", b)
	}
	if last := seen[len(seen)-1]; last.Phase != "frames" || last.Done != 8 || last.Total != 8 || seen[0].Phase != "copying" {
		t.Fatalf("progress: %+v", seen)
	}
	// The same bytes again: the turntable that's there, with nothing rendered.
	seen = nil
	again, err := renderTurntable(context.Background(), blender, cache, folder, "machines/x.obj", nil, set, func(p turnProgress) { seen = append(seen, p) })
	if err != nil || !again.Reused || len(seen) != 0 || again.Dir != res.Dir {
		t.Fatalf("again: %+v %v %+v", again, err, seen)
	}
	// A changed texture makes it again, in the same folder; so do other settings.
	os.WriteFile(filepath.Join(folder, "machines", "tex.png"), []byte("second"), 0o644)
	if r, err := renderTurntable(context.Background(), blender, cache, folder, "machines/x.obj", nil, set, nil); err != nil || r.Reused || r.Dir != res.Dir {
		t.Fatalf("changed texture: %+v %v", r, err)
	}
	set.Frames = 4
	if r, err := renderTurntable(context.Background(), blender, cache, folder, "machines/x.obj", nil, set, nil); err != nil || r.Reused || len(r.Frames) != 4 {
		t.Fatalf("fewer frames: %+v %v", r, err)
	}
	if fileExists(filepath.Join(folder, "machines", "x-turntable", "f07.webp")) {
		t.Error("the old frames should go when it's made again")
	}
	// Someone's own folder of that name is left alone.
	r, err := renderTurntable(context.Background(), blender, cache, folder, "machines/y.stl", nil, set, nil)
	if err != nil || r.Dir != "machines/y-turntable-2" {
		t.Fatalf("y: %+v %v", r, err)
	}
	if b, _ := os.ReadFile(filepath.Join(folder, "machines", "y-turntable", "notes.txt")); string(b) != "mine" {
		t.Error("someone's own folder was touched")
	}
	// What the script says when it can't read a model comes back as it is.
	writeFiles(t, folder, map[string]string{"broken.ply": "ply\nformat ascii 1.0\nend_header\n"})
	if _, err := renderTurntable(context.Background(), blender, cache, folder, "broken.ply", nil, set, nil); err == nil || err.Error() != "Blender couldn't read it: not a model" {
		t.Fatalf("broken: %v", err)
	}
	if fileExists(filepath.Join(folder, "broken-turntable")) {
		t.Error("a failed turntable left a folder")
	}
}

func TestStoppingATurntableStopsItsBlenderAndLeavesNoFrames(t *testing.T) {
	blender := fakeTurnBlender(t)
	folder, cache := t.TempDir(), t.TempDir()
	writeFiles(t, folder, map[string]string{"slow.stl": "solid s\nendsolid s\n"})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	start := time.Now()
	_, err := renderTurntable(ctx, blender, cache, folder, "slow.stl", nil, turnSettings{Frames: 72, Px: 32, Samples: 1}, func(p turnProgress) {
		if p.Phase == "frames" && p.Done == 2 {
			cancel()
		}
	})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("stopped: %v", err)
	}
	if took := time.Since(start); took > 8*time.Second {
		t.Fatalf("stopping took %s", took)
	}
	entries, _ := os.ReadDir(folder)
	if len(entries) != 1 {
		t.Fatalf("the chat's folder: %v", entries)
	}
	b, err := os.ReadFile(filepath.Join(cache, "pid"))
	if err != nil {
		t.Fatal("the stand-in never wrote its pid")
	}
	pid, _ := strconv.Atoi(string(b))
	for end := time.Now().Add(5 * time.Second); ; time.Sleep(50 * time.Millisecond) {
		if err := syscall.Kill(pid, 0); errors.Is(err, syscall.ESRCH) {
			break
		}
		if time.Now().After(end) {
			t.Fatalf("Blender (pid %d) is still running", pid)
		}
	}
}

func TestTheModelIsToldAboutATurntablesFrames(t *testing.T) {
	folder := t.TempDir()
	writeFiles(t, folder, map[string]string{"machines/x.obj": "v 0 0 0\nv 2 0 0\nv 0 1 0\nf 1 2 3\n"})
	files := []AttachedFile{{Path: "machines/x.obj", Bytes: 30, Turntable: "machines/x-turntable"}}
	for i := 0; i < 72; i++ {
		p := "machines/x-turntable/f" + strings.Repeat("0", 2-len(strconv.Itoa(i))) + strconv.Itoa(i) + ".webp"
		writeFiles(t, folder, map[string]string{p: string(webpOf(800, 800, true))})
		files = append(files, AttachedFile{Path: p, Bytes: 30, Made: "turntable", From: "machines/x.obj"})
	}
	writeFiles(t, folder, map[string]string{"machines/x-turntable/poster.webp": string(webpOf(800, 800, true))})
	files = append(files, AttachedFile{Path: "machines/x-turntable/poster.webp", Bytes: 30, Made: "turntable", From: "machines/x.obj"})
	_, note := describeAttachments(folder, files, 24000)
	for _, want := range []string{
		"- `machines/x-turntable/f00.webp` to `machines/x-turntable/f71.webp`: 72 pictures, WebP, 800 × 800, transparent background, 2 KB in all, numbered 00 to 71. A turntable of `machines/x.obj` that Chimera rendered: one full turn in 72 frames, 5° apart, so frame n is n × 5° on from frame 0, a three-quarter view; as the number goes up it turns counterclockwise seen from above (its near side moves right)",
		"- `machines/x-turntable/poster.webp`: picture, WebP, 800 × 800, transparent background, 30 bytes. Frame 0 of the turntable of `machines/x.obj`, a little sharper: to show until the frames load",
		"Without a 3D library, its turntable will do: Chimera rendered 72 frames of it turning, in `machines/x-turntable/`",
		"Only these facts about the pictures come with this message, not what they show.",
	} {
		if !strings.Contains(note, want) {
			t.Errorf("missing %q in:\n%s", want, note)
		}
	}
	if got := turnWords("m.glb", 36); !strings.Contains(got, "36 frames, 10° apart, so frame n is n × 10°") {
		t.Errorf("36 frames: %s", got)
	}
	if got := turnWords("m.glb", 48); !strings.Contains(got, "7.5° apart") {
		t.Errorf("48 frames: %s", got)
	}
	// A model that couldn't be turned says why.
	_, note = describeAttachments(folder, []AttachedFile{{Path: "machines/x.obj", Bytes: 30, NoTurn: "Blender can't read a text (ASCII) FBX; save it as a binary FBX or as glTF"}}, 24000)
	if !strings.Contains(note, "No turntable could be made of it here: Blender can't read a text (ASCII) FBX") {
		t.Errorf("no turntable:\n%s", note)
	}
}

// Real Blender, when there's one here (CHIMERA_TEST_BLENDER picks it): a cube from an
// OBJ with its .mtl and texture, and a PLY, on the CPU, small, in the sandbox.
func TestRealBlenderMakesATurntable(t *testing.T) {
	blender := testBlender(t)
	if !canSandbox() {
		t.Skip("no sandbox here")
	}
	folder, cache := t.TempDir(), t.TempDir()
	writeFiles(t, folder, map[string]string{
		"box/cube.obj": "mtllib cube.mtl\nv -1 -1 0\nv 1 -1 0\nv 1 1 0\nv -1 1 0\nv -1 -1 2\nv 1 -1 2\nv 1 1 2\nv -1 1 2\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nusemtl paint\n" +
			"f 1/1 2/2 3/3 4/4\nf 5/1 8/2 7/3 6/4\nf 1/1 5/2 6/3 2/4\nf 2/1 6/2 7/3 3/4\nf 3/1 7/2 8/3 4/4\nf 4/1 8/2 5/3 1/4\n",
		"box/cube.mtl": "newmtl paint\nKd 1 1 1\nmap_Kd paint.png\n",
		"tri.ply":      "ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n0 0 0 255 0 0\n1 0 0 0 255 0\n0 0 1 0 0 255\n3 0 1 2\n",
	})
	os.WriteFile(filepath.Join(folder, "box", "paint.png"), pngOf(t, cutout(8, 8)), 0o644)
	set := turnSettings{Frames: 4, Px: 96, Samples: 2, Start: 45}
	for _, model := range []string{"box/cube.obj", "tri.ply"} {
		res, err := renderTurntable(context.Background(), blender, cache, folder, model, nil, set, nil)
		if err != nil {
			t.Fatalf("%s: %v", model, err)
		}
		if len(res.Frames) != 4 || !strings.HasSuffix(res.Poster, "poster.webp") && !strings.HasSuffix(res.Poster, "poster.png") {
			t.Fatalf("%s: %+v", model, res)
		}
		full := filepath.Join(folder, filepath.FromSlash(res.Frames[0]))
		x := readFacts(full, res.Frames[0], 0, func(string) bool { return false })
		if x.Kind != "picture" || x.Width != 96 || x.Height != 96 || x.Alpha == "" {
			t.Fatalf("%s's first frame: %+v", model, x)
		}
		if res.Made.Faces == 0 || len(res.Made.Size) != 3 {
			t.Fatalf("%s's record: %+v", model, res.Made)
		}
	}
	// A file Blender can't read comes back as a reason, with no folder left.
	writeFiles(t, folder, map[string]string{"junk.glb": "glTF not really"})
	if _, err := renderTurntable(context.Background(), blender, cache, folder, "junk.glb", nil, set, nil); err == nil || strings.Contains(err.Error(), folder) {
		t.Fatalf("junk: %v", err)
	}
	if fileExists(filepath.Join(folder, "junk-turntable")) {
		t.Error("a failed turntable left its folder")
	}
}

func TestBlendersKernelCacheIsAPathItCanUse(t *testing.T) {
	for p, want := range map[string]bool{
		"/Users/fx/Library/Application Support/Chimera/blender-cache": false, // a space, and under /Users: both crashed Blender
		"/Users/fx/Library/Caches/Chimera/blender-kernels":            false, // under /Users, which the sandbox hides
		"/Volumes/Envoy/cache":                           false,
		"/private/tmp/a b/cache":                         false,
		"/private/tmp/café/cache":                        false,
		"relative/cache":                                 false,
		"/var/folders/6y/3vdw/C/chimera-blender-kernels": true,
		"/private/tmp/claude-501/x_y-z.1/cache":          true,
	} {
		if got := cacheSafe(p); got != want {
			t.Errorf("cacheSafe(%q) = %v", p, got)
		}
	}
	if d := turnCacheDir(); d != "" && !cacheSafe(d) {
		t.Errorf("the cache folder this computer gets isn't safe: %q", d)
	} else if runtime.GOOS == "darwin" && !strings.HasPrefix(d, "/var/folders/") && !strings.HasPrefix(d, os.TempDir()) {
		t.Errorf("on a Mac it should be macOS's own cache folder or the temporary one: %q", d)
	}
}

func TestATurntableThatCrashesOnTheGPUIsMadeOnTheProcessor(t *testing.T) {
	blender := fakeTurnBlender(t)
	folder, cache := t.TempDir(), t.TempDir()
	writeFiles(t, folder, map[string]string{"gpucrash.stl": "solid s\nendsolid s\n"})
	var logged bytes.Buffer
	log.SetOutput(&logged)
	defer log.SetOutput(os.Stderr)
	var phases []string
	set := turnSettings{Frames: 4, Px: 32, Samples: 1, Start: 45, GPU: true}
	res, err := renderTurntable(context.Background(), blender, cache, folder, "gpucrash.stl", nil, set, func(p turnProgress) { phases = append(phases, p.Phase) })
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Frames) != 4 || res.Made.Device != "CPU, after the GPU stopped" || !res.Made.Settings.GPU {
		t.Fatalf("%+v", res.Made)
	}
	if !strings.Contains(strings.Join(phases, " "), "cpu") {
		t.Errorf("phases: %v", phases)
	}
	if l := logged.String(); !strings.Contains(l, "gpucrash.stl: Blender stopped on the GPU after 0 of 4 frames") || !strings.Contains(l, "ccl::MetalKernelPipeline::compile()") {
		t.Errorf("the log: %s", l)
	}
	if got := turnStatus("gpucrash.stl", turnProgress{Phase: "cpu"}, 1, 1); !strings.Contains(got, "on the processor instead") {
		t.Errorf("status: %s", got)
	}
	// Asked for the GPU again, the one made on the processor is used as it is.
	if again, err := renderTurntable(context.Background(), blender, cache, folder, "gpucrash.stl", nil, set, nil); err != nil || !again.Reused {
		t.Fatalf("again: %+v %v", again, err)
	}
}
