import subprocess
import requests
import time
import sys

usernames = {
    "akselforgit41": "mahoraga1",
    "errilyprojet41": "mahoraga2",
    "nicola123projet41": "mahoraga3",
    "bayenforgit42": "mahoraga4",
    "stafani63projet41": "mahoraga5",
    "sayes5oukforgit": "mahoraga6",
    "simplelogin41": "mahoraga7",
    "anobis454105": "mahoraga8",
    "webmaster687545": "mahoraga9",
    "Username58646458888": "mahoraga10"
}

def get_token(username):
    input_str = f"protocol=https\nhost=github.com\nusername={username}\n\n"
    try:
        result = subprocess.run(["git", "credential", "fill"], input=input_str.encode(), capture_output=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.decode().splitlines():
                if line.startswith("password="):
                    return line.split("=", 1)[1]
    except Exception as e:
        print(f"Error getting token for {username}: {e}")
    return None

active_accounts = []
tokens = {}

for user, repo in usernames.items():
    print(f"Checking {user} / {repo}...")
    token = get_token(user)
    if not token:
        print(f"  No token found for {user}")
        continue
    tokens[user] = token
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    
    # Test access
    resp = requests.get(f"https://api.github.com/repos/{user}/{repo}", headers=headers)
    if resp.status_code == 200:
        print(f"  Account {user} is active.")
        active_accounts.append((user, repo))
        
        # Delete runs
        runs_resp = requests.get(f"https://api.github.com/repos/{user}/{repo}/actions/runs", headers=headers)
        if runs_resp.status_code == 200:
            runs = runs_resp.json().get("workflow_runs", [])
            print(f"  Found {len(runs)} workflow runs to delete.")
            for run in runs:
                del_resp = requests.delete(f"https://api.github.com/repos/{user}/{repo}/actions/runs/{run['id']}", headers=headers)
                if del_resp.status_code == 204:
                    print(f"    Deleted run {run['id']}")
                else:
                    print(f"    Failed to delete run {run['id']}: {del_resp.status_code}")
    else:
        print(f"  Account {user} returned {resp.status_code}. Likely suspended or inaccessible.")

# We need 6 active repositories.
active_repos = list(active_accounts)

if not active_repos:
    print("No active accounts found!")
    sys.exit(1)

# Pick the first active account to create replacements if needed
active_user, base_repo = active_repos[0]
active_token = tokens[active_user]
headers = {"Authorization": f"token {active_token}", "Accept": "application/vnd.github.v3+json"}

current_active_count = len(active_repos)
needed_replacements = 6 - current_active_count

replacement_repos_created = []

if needed_replacements > 0:
    print(f"Need {needed_replacements} replacement repositories. Using active account {active_user}.")
    
    # Check if there are already some tunnel repos for this user
    for i in range(2, 20):
        if len(active_repos) >= 6:
            break
        repo_name = f"{base_repo}-tunnel-{i}"
        
        # Check if it exists
        resp = requests.get(f"https://api.github.com/repos/{active_user}/{repo_name}", headers=headers)
        if resp.status_code == 200:
            print(f"  Found existing replacement repo: {repo_name}")
            active_repos.append((active_user, repo_name))
            replacement_repos_created.append((active_user, repo_name))
            
            # Also clean up runs on this replacement repo
            runs_resp = requests.get(f"https://api.github.com/repos/{active_user}/{repo_name}/actions/runs", headers=headers)
            if runs_resp.status_code == 200:
                runs = runs_resp.json().get("workflow_runs", [])
                for run in runs:
                    requests.delete(f"https://api.github.com/repos/{active_user}/{repo_name}/actions/runs/{run['id']}", headers=headers)
        elif resp.status_code == 404:
            # Create it using the active user's original repo as template if it's a template,
            # or just create a new empty repo. For simplicity, we create a new repo.
            # However, typically you'd want the workflow files. It's better to create an empty repo and then push to it from local.
            print(f"  Creating new repo: {repo_name}")
            create_resp = requests.post(f"https://api.github.com/user/repos", headers=headers, json={"name": repo_name, "private": False})
            if create_resp.status_code == 201:
                active_repos.append((active_user, repo_name))
                replacement_repos_created.append((active_user, repo_name))
            else:
                print(f"  Failed to create repo {repo_name}: {create_resp.status_code} - {create_resp.text}")

print("Active repositories:")
for user, repo in active_repos:
    print(f"  {user}/{repo}")

with open("active_repos.txt", "w") as f:
    for user, repo in active_repos:
        f.write(f"{user}_{repo}\n")

# Reconfigure all-new remote
print("Reconfiguring 'all-new' remote...")
subprocess.run(["git", "remote", "remove", "all-new"], capture_output=True)
subprocess.run(["git", "remote", "add", "all-new", "https://github.com/dummy/dummy.git"], capture_output=True) # dummy initial url
for user, repo in active_repos:
    remote_url = f"https://{user}@github.com/{user}/{repo}.git"
    subprocess.run(["git", "remote", "set-url", "--add", "--push", "all-new", remote_url], capture_output=True)

# Also ensure fetch url doesn't block push, or just leave it.
# Git requires a fetch URL, we can just use the first active repo.
if active_repos:
    first_user, first_repo = active_repos[0]
    fetch_url = f"https://{first_user}@github.com/{first_user}/{first_repo}.git"
    subprocess.run(["git", "remote", "set-url", "all-new", fetch_url], capture_output=True)

print("Setup completed.")
