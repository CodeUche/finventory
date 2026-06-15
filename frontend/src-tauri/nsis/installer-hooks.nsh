; Audity NSIS installer hooks

!macro customInstall
  ; ── 1. Remove legacy "Finventory" installation if present ──────────────────
  ; The app was previously published as "Finventory" (com.finventory.app).
  ; Silently uninstall it so users don't end up with both entries in Apps & Features.
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Finventory" "UninstallString"
  ${If} $0 != ""
    nsExec::ExecToLog '"$0" /S'
  ${EndIf}
  ReadRegStr $0 HKCU "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Finventory" "UninstallString"
  ${If} $0 != ""
    nsExec::ExecToLog '"$0" /S'
  ${EndIf}

  ; ── 2. WebView2 loopback exemption ─────────────────────────────────────────
  ; Allows the desktop app to reach the cloud API through WebView2.
  nsExec::ExecToLog '"$WINDIR\System32\CheckNetIsolation.exe" LoopbackExempt -a -n="Microsoft.Win32WebViewHost_cw5n1h2txyewy"'

  ; ── 3. Force Windows to rebuild the icon cache ─────────────────────────────
  ; Without this, users see the old Finventory icon on taskbar and Start menu
  ; even after reinstalling. Deleting these files causes Windows to regenerate
  ; them automatically; ie4uinit refreshes running Explorer immediately.
  Delete "$LOCALAPPDATA\IconCache.db"
  Delete "$LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache_*.db"
  Delete "$LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache.db"
  nsExec::ExecToLog 'ie4uinit.exe -show'
!macroend

!macro customUninstall
  nsExec::ExecToLog '"$WINDIR\System32\CheckNetIsolation.exe" LoopbackExempt -d -n="Microsoft.Win32WebViewHost_cw5n1h2txyewy"'
!macroend
