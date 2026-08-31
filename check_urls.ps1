$repos = @(
    "akselforgit41_mahoraga1",
    "errilyprojet41_mahoraga2",
    "nicola123projet41_mahoraga3",
    "bayenforgit42_mahoraga4",
    "stafani63projet41_mahoraga5",
    "sayes5oukforgit_mahoraga6",
    "simplelogin41_mahoraga7",
    "anobis454105_mahoraga8",
    "webmaster687545_mahoraga9",
    "Username58646458888_mahoraga10"
)

foreach ($repo in $repos) {
    $url = "https://ntfy.sh/dahaka_tunnels_$repo/json?poll=1"
    $messages = curl.exe -s $url
    if ([string]::IsNullOrEmpty($messages)) {
        Write-Host "REPO: $repo -> No messages found yet."
        continue
    }
    $localMatches = [regex]::Matches($messages, "https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    if ($localMatches.Count -gt 0) {
        $lastUrl = $localMatches[$localMatches.Count - 1].Value
        try {
            $shortUrlResp = Invoke-RestMethod -Uri "https://cleanuri.com/api/v1/shorten" -Method Post -Body @{url=$lastUrl} -ErrorAction Stop
            $shortUrl = $shortUrlResp.result_url
            Write-Host "REPO: $repo -> $shortUrl ==> $lastUrl"
        } catch {
            Write-Host "REPO: $repo -> $lastUrl"
        }
    } else {
        Write-Host "REPO: $repo -> No URL found yet."
    }
}
