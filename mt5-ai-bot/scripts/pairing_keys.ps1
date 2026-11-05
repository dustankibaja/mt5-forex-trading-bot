# Windows-only secure pairing keys: encrypted to the current Windows user
# with DPAPI. Secrets persist across normal backend restarts and reboots.
# Never print secrets in logs or save them as plaintext.
function Get-PrivatePairingCredentials {
    param(
        [Parameter(Mandatory=$true)][string] $Path,
        [switch] $CreateIfMissing,
        [switch] $Rotate
    )
    Add-Type -AssemblyName System.Security
    $scope = [System.Security.Cryptography.DataProtectionScope]::CurrentUser
    $target = [System.IO.Path]::GetFullPath($Path)
    if ((Test-Path -LiteralPath $target) -and -not $Rotate) {
        try {
            $cipher = [System.IO.File]::ReadAllBytes($target)
            $plain = [System.Security.Cryptography.ProtectedData]::Unprotect(
                $cipher, $null, $scope
            )
            $data = [System.Text.Encoding]::UTF8.GetString($plain) |
                ConvertFrom-Json
            if ($data.version -ne 1 -or
                $data.read_token -notmatch '^[A-Za-z0-9_-]{40,}$' -or
                $data.control_token -notmatch '^[A-Za-z0-9_-]{40,}$' -or
                $data.read_token -eq $data.control_token) {
                throw 'Encrypted credentials did not pass validation.'
            }
            return $data
        } catch {
            throw ('Could not decrypt persistent pairing keys for current ' +
                'Windows user. Do not overwrite them automatically. ' +
                'Use -RotateKeys only if re-pairing all phones is intended. ' +
                $_.Exception.Message)
        }
    }
    if ((-not $CreateIfMissing) -and (-not $Rotate)) {
        throw 'No saved pairing credentials. Start the DEMO bridge first.'
    }
    $gen = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        function New-PrivateToken {
            $bytes = New-Object byte[] 48
            $gen.GetBytes($bytes)
            return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        }
        $data = [pscustomobject]@{
            version = 1
            read_token = (New-PrivateToken)
            control_token = (New-PrivateToken)
        }
        $plain = [System.Text.Encoding]::UTF8.GetBytes(
            ($data | ConvertTo-Json -Compress)
        )
        $encrypted = [System.Security.Cryptography.ProtectedData]::Protect(
            $plain, $null, $scope
        )
        $directory = Split-Path -Parent $target
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
        $temp = $target + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
        try {
            [System.IO.File]::WriteAllBytes($temp, $encrypted)
            Move-Item -LiteralPath $temp -Destination $target -Force
        } finally {
            Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        }
        return $data
    } finally {
        $gen.Dispose()
    }
}
