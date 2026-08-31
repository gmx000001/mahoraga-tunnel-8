import subprocess
import requests
import re
import sys
import time

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
        pass
    return None

def get_tunnel_from_logs(user, repo, token):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # 1. Get runs
    runs_url = f"https://api.github.com/repos/{user}/{repo}/actions/runs"
    resp = requests.get(runs_url, headers=headers, params={"per_page": 1})
    if resp.status_code != 200:
        return f"Error: HTTP {resp.status_code}"
    
    runs = resp.json().get("workflow_runs", [])
    if not runs:
        return "No runs found"
    
    run = runs[0]
    run_id = run["id"]
    status = run["status"]
    
    # 2. Get jobs
    jobs_url = f"https://api.github.com/repos/{user}/{repo}/actions/runs/{run_id}/jobs"
    resp = requests.get(jobs_url, headers=headers)
    if resp.status_code != 200:
        return f"Error getting jobs: HTTP {resp.status_code}"
    
    jobs = resp.json().get("jobs", [])
    if not jobs:
        return "No jobs found"
    
    job_id = jobs[0]["id"]
    
    # 3. Get job logs
    logs_url = f"https://api.github.com/repos/{user}/{repo}/actions/jobs/{job_id}/logs"
    resp = requests.get(logs_url, headers=headers, allow_redirects=True)
    if resp.status_code != 200:
        return f"No logs yet (status: {status})"
    
    log_text = resp.text
    
    # Search for trycloudflare URL in logs
    # Format typically: "  https://*.trycloudflare.com" or similar
    matches = re.findall(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', log_text)
    if matches:
        # Return the last match
        return matches[-1]
    
    return f"Tunnel not started yet (status: {status})"

print(f"{'Repository':<35} | {'Status/Tunnel URL'}")
print("-" * 75)

for user, repo in usernames.items():
    token = get_token(user)
    if not token:
        print(f"{user}/{repo:<30} | No token found")
        continue
    
    tunnel = get_tunnel_from_logs(user, repo, token)
    print(f"{user}/{repo:<30} | {tunnel}")
