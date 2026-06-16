import sys
import json
import subprocess
import os

def main():
    try:
        # Cursor Command Hooks receive JSON on stdin
        input_data = sys.stdin.read()
        if not input_data:
            return

        payload = json.loads(input_data)
        command = payload.get("command", "").strip()

        # Intercept only git commit operations to act as an Agent Quality Gate
        if not command.startswith("git commit"):
            print(json.dumps({"block": False}))
            return

        root_dir = os.getcwd()
        errors = []

        # 1. Strict Backend Unit Tests (Core Intelligence Logic)
        backend_dir = os.path.join(root_dir, "backend")
        python_exe = os.path.join(backend_dir, "venv", "Scripts", "python.exe")
        
        if os.path.exists(python_exe):
            res_py = subprocess.run(
                [python_exe, "-m", "unittest", "test_operator_briefing"],
                cwd=backend_dir, capture_output=True, text=True
            )
            if res_py.returncode != 0:
                errors.append(f"🔥 CORE LOGIC BROKEN (Backend Unit Tests Failed):\n{res_py.stderr.strip()}")
        else:
            errors.append("⚠️ Python VENV not found. Cannot verify backend integrity.")

        # If any quality gates fail, BLOCK the commit.
        if errors:
            error_msg = "❌ PRE-COMMIT QUALITY GATE REJECTED\n\n" + "\n\n".join(errors) + "\n\n[WorldBase Hook] Fix the errors above before committing. Professional standards enforced."
            print(json.dumps({
                "block": True,
                "message": error_msg
            }))
            return

        # Passed all checks
        print(json.dumps({"block": False}))

    except Exception as e:
        # Professional fail-open: do not freeze the developer's git workflow if the hook itself crashes
        print(json.dumps({"block": False, "message": f"Hook execution warning: {str(e)}"}))

if __name__ == "__main__":
    main()
