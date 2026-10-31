"""A stand-in for Blender, for hydra_test.py: enough of `blender -b --factory-startup --python-exit-code N
[--python-expr CODE] --python script.py --` to check a long task's script, with a tiny bpy (bpy/) and a mathutils
without radians. It reports a failed script the way Blender 5 does: a traceback of the script's own frames on
stderr, then "Error: script failed, file: '<path>', exiting.", and exits with the --python-exit-code value.
hydra_test.py copies this folder to /var/tmp and writes an executable `blender` there: a #! line naming a system
Python with -I, then this file."""
import os, runpy, sys, traceback

sys.dont_write_bytecode = True  # -I ignores PYTHONDONTWRITEBYTECODE, and the sandbox blocks writes here anyway
HERE = os.path.dirname(os.path.realpath(__file__))
BANNER = "Blender 5.0.1 (hash test)"


def report(exc, script):
    """Prints a failed script's error the way Blender does: only the script's own frames."""
    if isinstance(exc, SyntaxError):  # no traceback header, just where it is
        lines = traceback.format_exception_only(type(exc), exc)
    else:
        real = os.path.realpath(script)
        frames = [f for f in traceback.extract_tb(exc.__traceback__)
                  if f.filename == script or os.path.realpath(f.filename) == real]
        lines = (["Traceback (most recent call last):\n"] + traceback.StackSummary.from_list(frames).format() +
                 traceback.format_exception_only(type(exc), exc))
    sys.stderr.write("".join(lines))
    sys.stderr.write("\nError: script failed, file: '%s', exiting.\n" % script)
    sys.stderr.flush()


def main(argv):
    args = argv[1:]
    if "--version" in args or "-v" in args:
        print(BANNER)
        return 0
    exit_code, actions, i = 0, [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            break
        if a in ("-b", "--background", "--factory-startup"):
            i += 1
        elif a == "--python-exit-code" and i + 1 < len(args):
            exit_code, i = int(args[i + 1]), i + 2
        elif a == "--python-expr" and i + 1 < len(args):
            actions.append(("expr", args[i + 1]))
            i += 2
        elif a in ("--python", "-P") and i + 1 < len(args):
            actions.append(("file", args[i + 1]))
            i += 2
        else:
            print("Error: unknown argument %r" % a, file=sys.stderr)
            return 1
    print(BANNER, flush=True)
    sys.path.insert(0, HERE)  # import bpy / import mathutils find the stubs
    sys.argv = list(argv)
    import bpy  # noqa: F401  (loaded before any script, as in Blender)
    for what, value in actions:
        try:
            if what == "expr":
                exec(compile(value, "<string>", "exec"), {"__name__": "__main__"})
            else:
                runpy.run_path(value, run_name="__main__")
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            print("Blender quit", flush=True)
            return code
        except BaseException as e:
            report(e, value if what == "file" else "<string>")
            print("Blender quit", flush=True)
            return exit_code
    print("Blender quit", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
