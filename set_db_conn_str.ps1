<#
.SYNOPSIS
    Sets the MICRO1_DB_CONN_STR environment variable used by db.py.

.DESCRIPTION
    Run this once per machine/user to persist the connection string,
    or run it in a session before launching your script for a
    temporary, process-only value. Adjust the connection string below
    to match your SQL Server host/instance/driver as needed.

.NOTES
    - "User" scope persists for the current Windows user across sessions.
    - "Machine" scope persists for all users (requires an elevated/
      Administrator PowerShell prompt).
    - Process scope only affects the current PowerShell session/process.
#>

param(
    [Parameter(Mandatory = $false)]
    [string]$ConnectionString = "mssql+pyodbc://@localhost/micro1?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes",

    [Parameter(Mandatory = $false)]
    [ValidateSet("Process", "User", "Machine")]
    [string]$Scope = "User"
)

[System.Environment]::SetEnvironmentVariable("MICRO1_DB_CONN_STR", $ConnectionString, $Scope)

# Also set it for the current session so it's usable immediately,
# regardless of which persistence scope was chosen.
$env:MICRO1_DB_CONN_STR = $ConnectionString

Write-Host "MICRO1_DB_CONN_STR set (scope: $Scope)." -ForegroundColor Green
Write-Host "Value: $ConnectionString"
