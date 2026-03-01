; Finventory NSIS installer hooks
; Applies the WebView2 loopback exemption so the desktop app can reach
; http://localhost:8000 (the Django backend). The exemption is persistent
; and stored in the Windows registry — it survives reboots.

!macro customInstall
  nsExec::ExecToLog '"$WINDIR\System32\CheckNetIsolation.exe" LoopbackExempt -a -n="Microsoft.Win32WebViewHost_cw5n1h2txyewy"'
!macroend

!macro customUninstall
  nsExec::ExecToLog '"$WINDIR\System32\CheckNetIsolation.exe" LoopbackExempt -d -n="Microsoft.Win32WebViewHost_cw5n1h2txyewy"'
!macroend
