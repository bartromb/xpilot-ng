; Installer for the self-contained Windows build.
;
; The build it packages is the portable layout: xpilot-ng-sdl.exe and
; xpilot-ng-server.exe at the root with their data in lib\ beside them and
; every mingw DLL alongside. Nothing here rewrites paths, so the installed
; copy is the same tree the .zip contains.
;
; Shortcuts do not set a working directory. They do not need to:
; Conf_anchor_datadir() moves the process to its own directory at startup, so
; the game finds lib\ however it was launched.

!include "MUI2.nsh"

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef SOURCE_DIR
  !define SOURCE_DIR "dist\xpilot-ng-windows"
!endif
!ifndef OUT_FILE
  !define OUT_FILE "xpilot-ng-setup.exe"
!endif
; Paths reach makensis as native Windows paths; the caller converts them,
; because an MSYS2 shell hands out POSIX ones that NSIS cannot open.
!ifndef LICENSE_FILE
  !define LICENSE_FILE "COPYING"
!endif

Name "XPilot NG ${VERSION}"
OutFile "${OUT_FILE}"
Unicode true
InstallDir "$PROGRAMFILES64\XPilot NG"
InstallDirRegKey HKLM "Software\XPilotNG" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_LICENSE "${LICENSE_FILE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "XPilot NG" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*"

  CreateDirectory "$SMPROGRAMS\XPilot NG"
  CreateShortCut "$SMPROGRAMS\XPilot NG\XPilot NG.lnk" \
                 "$INSTDIR\xpilot-ng-sdl.exe" "" "$INSTDIR\xpilot-ng-sdl.exe" 0
  CreateShortCut "$SMPROGRAMS\XPilot NG\XPilot NG Server.lnk" \
                 "$INSTDIR\xpilot-ng-server.exe"
  CreateShortCut "$SMPROGRAMS\XPilot NG\Uninstall.lnk" "$INSTDIR\uninstall.exe"

  WriteRegStr HKLM "Software\XPilotNG" "InstallDir" "$INSTDIR"

  ; Add/Remove Programs
  !define UNINST_KEY \
    "Software\Microsoft\Windows\CurrentVersion\Uninstall\XPilotNG"
  WriteRegStr   HKLM "${UNINST_KEY}" "DisplayName"     "XPilot NG"
  WriteRegStr   HKLM "${UNINST_KEY}" "DisplayVersion"  "${VERSION}"
  WriteRegStr   HKLM "${UNINST_KEY}" "Publisher"       "XPilot NG contributors"
  WriteRegStr   HKLM "${UNINST_KEY}" "URLInfoAbout" \
                "https://github.com/bartromb/xpilot-ng"
  WriteRegStr   HKLM "${UNINST_KEY}" "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegStr   HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1

  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\XPilot NG\XPilot NG.lnk"
  Delete "$SMPROGRAMS\XPilot NG\XPilot NG Server.lnk"
  Delete "$SMPROGRAMS\XPilot NG\Uninstall.lnk"
  RMDir  "$SMPROGRAMS\XPilot NG"

  Delete "$INSTDIR\uninstall.exe"
  ; Only what this installer put there. Named explicitly rather than
  ; RMDir /r "$INSTDIR", which would take the whole directory with it if
  ; someone installed into one they were already using.
  RMDir /r "$INSTDIR\lib"
  RMDir /r "$INSTDIR\share"
  Delete "$INSTDIR\*.exe"
  Delete "$INSTDIR\*.dll"
  Delete "$INSTDIR\COPYING"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\BUILDING.md"
  RMDir "$INSTDIR"

  DeleteRegKey HKLM \
    "Software\Microsoft\Windows\CurrentVersion\Uninstall\XPilotNG"
  DeleteRegKey HKLM "Software\XPilotNG"
SectionEnd
