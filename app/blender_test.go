package main

import (
	"os"
	"path/filepath"
	"sort"
	"testing"
)

func TestBundleVersionNewestFirst(t *testing.T) {
	root := t.TempDir()
	for name, v := range map[string]string{"Blender.app": "4.5.4", "Blender 2.app": "5.2.2", "Blender 3.app": "5.0.1"} {
		os.MkdirAll(filepath.Join(root, name, "Contents"), 0o755)
		os.WriteFile(filepath.Join(root, name, "Contents", "Info.plist"), []byte("<plist><dict>\n<key>CFBundleShortVersionString</key>\n\t<string>"+v+"</string>\n</dict></plist>"), 0o644)
	}
	apps, _ := filepath.Glob(filepath.Join(root, "Blender*.app"))
	sort.SliceStable(apps, func(i, j int) bool { return versionLess(bundleVersion(apps[j]), bundleVersion(apps[i])) })
	if filepath.Base(apps[0]) != "Blender 2.app" || filepath.Base(apps[2]) != "Blender.app" {
		t.Fatalf("want newest first, got %v", apps)
	}
}
