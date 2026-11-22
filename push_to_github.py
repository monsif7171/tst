# -*- coding: utf-8 -*-
"""
Teryaq GitHub Auto-Deployer
Automates pushing Teryaq code to GitHub, fixing Git identity, and handling branch conflicts.
"""
import os
import sys
import subprocess


def run_cmd(cmd_list, check=False):
    """Run a command safely without shell=True and return (stdout, stderr, returncode)."""
    res = subprocess.run(
        cmd_list,
        shell=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="ignore",
    )
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed [{res.returncode}]: {' '.join(cmd_list)}\n{res.stderr}")
    return res.stdout.strip(), res.stderr.strip(), res.returncode


def print_banner():
    print("=" * 65)
    print("      Teryaq Smart Auto-Push Tool for GitHub")
    print("=" * 65)


def check_and_fix_identity():
    """Check git user.name and user.email and prompt if missing."""
    name, _, code_name = run_cmd(["git", "config", "user.name"])
    email, _, code_email = run_cmd(["git", "config", "user.email"])

    if code_name != 0 or not name or code_email != 0 or not email:
        print("\n[!] Warning: Git user identity is not configured on this machine.")
        print("    This is what causes the 'Please tell me who you are' error.\n")

        default_name = name or "Monsif Abbas"
        new_name = input(f"Enter your GitHub name [{default_name}]: ").strip() or default_name

        default_email = email or "monsifabbas09@gmail.com"
        new_email = input(f"Enter your GitHub email [{default_email}]: ").strip() or default_email

        run_cmd(["git", "config", "--global", "user.name", new_name])
        run_cmd(["git", "config", "--global", "user.email", new_email])
        print(f"[OK] Identity configured: {new_name} <{new_email}>\n")
    else:
        print(f"[*] Current Git identity: {name} <{email}>")


def main():
    print_banner()

    # 1. Check Git Installation
    _, _, git_code = run_cmd(["git", "--version"])
    if git_code != 0:
        print("[X] Error: Git is not installed on this machine! Please install it first.")
        sys.exit(1)

    # 2. Check and fix identity
    check_and_fix_identity()

    # 3. Check if repository is initialized
    if not os.path.exists(".git"):
        print("\n[*] Initializing a new local Git repository...")
        run_cmd(["git", "init"])
        print("[OK] Repository initialized.")

    # 4. Check Remote URL
    remotes_out, _, _ = run_cmd(["git", "remote", "-v"])
    current_remote = ""
    for line in remotes_out.splitlines():
        if "origin" in line and "(push)" in line:
            parts = line.split()
            if len(parts) >= 2:
                current_remote = parts[1]
                break

    print("-" * 65)
    if current_remote:
        print(f"[*] Current linked repository:\n    -> {current_remote}")
        change = input("Use this URL? [Y/n] (or paste a new URL): ").strip()
        if change.lower() in ("n", "no") or change.startswith("http"):
            new_remote = change if change.startswith("http") else input("Paste the new GitHub repository URL: ").strip()
            if new_remote:
                run_cmd(["git", "remote", "remove", "origin"])
                run_cmd(["git", "remote", "add", "origin", new_remote])
                current_remote = new_remote
                print(f"[OK] Remote URL updated to: {current_remote}")
    else:
        new_remote = input("Paste GitHub repository URL (e.g., https://github.com/USER/REPO.git): ").strip()
        while not new_remote:
            new_remote = input("Please enter a valid URL: ").strip()
        run_cmd(["git", "remote", "add", "origin", new_remote])
        current_remote = new_remote
        print(f"[OK] Repository linked: {current_remote}")

    # 5. Commit Message
    print("-" * 65)
    default_msg = "Cloud deployment updates and config for Teryaq v2.3"
    msg = input(f"Enter commit message [{default_msg}]: ").strip() or default_msg

    # 6. Add & Commit
    print("\n[*] Staging files (git add .)...")
    run_cmd(["git", "add", "."])

    print("[*] Committing changes locally (git commit)...")
    commit_out, commit_err, commit_code = run_cmd(["git", "commit", "-m", msg])
    if commit_code != 0:
        if "nothing to commit" in commit_out or "nothing to commit" in commit_err:
            print("[i] Nothing new to commit. Proceeding directly to push.")
        else:
            print(f"[!] Commit notice:\n{commit_err or commit_out}")
    else:
        print("[OK] Changes committed successfully.")

    # 7. Ensure Branch Name is 'main'
    branch_name = "main"
    run_cmd(["git", "branch", "-M", branch_name])

    # 8. Push
    repo_display_url = current_remote[:-4] if current_remote.endswith(".git") else current_remote
    print(f"\n[*] Pushing to GitHub on branch ({branch_name})...")
    _, push_err, push_code = run_cmd(["git", "push", "-u", "origin", branch_name])

    if push_code == 0:
        print("\n[OK] Successfully pushed to GitHub!")
        print("[*] You can now view your repository (including requirements.txt & render.yaml) at:")
        print(f"    -> {repo_display_url}")
    else:
        print("\n[!] Warning: Normal push was rejected.")
        print(f"    Likely cause: Remote repository has conflicting files or history.\nDetails:\n{push_err}")

        force_choice = input("\nDo you want to Force Push and overwrite the remote repo? [Y/n]: ").strip().lower()
        if force_choice in ("", "y", "yes"):
            print("[*] Force pushing (git push --force)...")
            _, f_err, f_code = run_cmd(["git", "push", "-u", "origin", branch_name, "--force"])
            if f_code == 0:
                print("\n[OK] Force push succeeded! All files updated on GitHub.")
                print(f"[*] Repository URL: {repo_display_url}")
            else:
                print(f"\n[X] Force push failed: {f_err}")
        else:
            print("[X] Push cancelled.")

    print("\n" + "=" * 65)
    print("Next Steps in Render:")
    print("1. Open Render.com and ensure Branch is set to: main")
    print("2. Ensure Root Directory is completely empty (Leave Empty).")
    print("3. Click Manual Deploy -> Deploy latest commit.")
    print("=" * 65)


if __name__ == "__main__":
    main()