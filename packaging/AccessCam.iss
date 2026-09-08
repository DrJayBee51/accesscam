; AccessCam installer, built with Inno Setup 6 (https://jrsoftware.org/isinfo.php).
;
;     iscc packaging\AccessCam.iss
;
; Assumes the PyInstaller build already exists at dist\AccessCam\ - build it
; first with `pyinstaller packaging\accesscam.spec`.
;
; Deliberately a per-user install with no elevation required to run or to
; install. AccessCam wants administrator rights for hover-driven UI (see
; docs/RUNNING.md on UIPI), but requiring them here would lock out anyone who
; is not an administrator of their own machine - a real case in the schools
; and rehab centres this is aimed at. The app says so in its own window (the
; elevation banner) and offers a way up from there; the installer's job is
; only to get it onto the machine.

#define AppVersion GetVersionNumbersString(SourcePath + "..\dist\AccessCam\AccessCam.exe")

[Setup]
AppId={{6B6E2A0E-6E1B-4C6B-9A4A-2E7B7B5A2F41}
AppName=AccessCam
AppVersion={#AppVersion}
AppPublisher=John Borek
AppPublisherURL=https://github.com/DrJayBee51/accesscam
AppSupportURL=https://github.com/DrJayBee51/accesscam
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\AccessCam
DefaultGroupName=AccessCam
; lowest, not admin: see the note above. autopf resolves to a per-user
; directory when not elevated and Program Files when it is, so the same
; script serves both without a second code path.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
OutputDir=..\dist\installer
OutputBaseFilename=AccessCam-Setup-{#AppVersion}
SetupIconFile=..\assets\accesscam.ico
UninstallDisplayIcon={app}\AccessCam.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
LicenseFile=..\LICENSE
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
; Ticked by default, and the only thing in this installer that asks for
; administrator rights. AccessCam is close to useless unelevated - UIPI drops
; its input for on-screen keyboards and for any window running as
; administrator - and the one route to elevation that never raises a UAC
; prompt is a scheduled task, which needs administrator rights to *create*.
; Doing it here spends that prompt while a mouse is still in someone's hand.
; Declining leaves AccessCam installed and working, with the Application tab
; offering the same thing later.
Name: "elevated"; Description: "&Always run AccessCam with administrator rights (asks once, now)"; \
    GroupDescription: "Elevation:"

[Files]
Source: "..\dist\AccessCam\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Still installed although nothing shortcuts to it any more: it is the escape
; hatch for a machine where AccessCam's own handover does not work, and
; RUNNING.md tells people to point a shortcut at it.
Source: "..\tools\launch-elevated.vbs"; DestDir: "{app}"; Flags: ignoreversion

; PyInstaller 6 relocates everything non-binary under _internal\ to keep the
; app folder tidy, which is fine for artwork and DLLs nobody goes looking for
; but defeats the point of a licence notice: it has to be somewhere a curious
; user - or their IT department - finds it without digging. Placed at the
; installed root, sourced straight from the repository rather than through
; PyInstaller, since installed layout is this script's job, not the build's.
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\packaging\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion

[Icons]
; One entry, not two. AccessCam hands over to its own elevated copy through
; the startup task whenever it finds itself unelevated, so every way of
; starting it - this shortcut, the desktop icon, a taskbar pin, the exe itself
; - ends up elevated. A second "start elevated" entry beside this one would
; only imply that this one is not.
Name: "{group}\AccessCam"; Filename: "{app}\AccessCam.exe"
Name: "{group}\Uninstall AccessCam"; Filename: "{uninstallexe}"
Name: "{autodesktop}\AccessCam"; Filename: "{app}\AccessCam.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AccessCam.exe"; Description: "Launch AccessCam now"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
; PyInstaller's own output only. Config (config.json) and the log live in
; %APPDATA%\AccessCam and are deliberately left alone below - settings tuned
; over days of real use are not the installer's to discard.
Type: filesandordirs; Name: "{app}"

[Code]
const
  TaskName = 'AccessCam';

function TaskExists(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('schtasks.exe', '/query /tn ' + TaskName, '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
  Log('AccessCam: logon task "' + TaskName + '" present: ' + IntToStr(Ord(Result)));
end;

procedure ReportTaskRemovalFailed(const Detail: String);
var
  Msg: String;
begin
  Msg := 'AccessCam was uninstalled, but its "start at logon" task could ' +
    'not be removed' + Detail + '. It will fail harmlessly at every future ' +
    'logon, pointing at software that is no longer there.' +
    Chr(13) + Chr(10) + Chr(13) + Chr(10) +
    'Remove it yourself from an Administrator prompt with:' +
    Chr(13) + Chr(10) + '  schtasks /delete /tn ' + TaskName + ' /f';
  Log('AccessCam: ' + Msg);
  // A silent/unattended uninstall (an IT deployment script, say) must never
  // block on a dialog nobody is watching to click - it would hang forever,
  // which is a far worse failure than a task that outlives the app.
  if not UninstallSilent() then
    MsgBox(Msg, mbInformation, MB_OK);
end;

procedure RemoveLogonTask();
var
  ResultCode: Integer;
begin
  if not TaskExists() then
    exit;

  // Plain attempt first, no elevation prompt. The task was registered with
  // /rl highest, which needs an elevated process to *create* - but deletion
  // does not carry the same restriction for a task's own creator, and asking
  // for administrator rights when they may not be needed is exactly the
  // instinct M4.4 argued against.
  Log('AccessCam: removing the logon task without elevation');
  Exec('schtasks.exe', '/delete /tn ' + TaskName + ' /f', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);

  if not TaskExists() then
  begin
    Log('AccessCam: logon task removed');
    exit;
  end;

  // Only now ask - ShellExec's 'runas' verb prompts UAC for this one command,
  // not for the whole uninstaller, the same on-demand pattern AccessCam's own
  // "Restart as administrator" button uses (main_window.py, relaunch_elevated).
  Log('AccessCam: unelevated removal did not take - asking for elevation');
  if not ShellExec('runas', 'schtasks.exe', '/delete /tn ' + TaskName + ' /f',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Log('AccessCam: the elevation prompt was declined or failed to launch');
    ReportTaskRemovalFailed(' automatically');
    exit;
  end;

  if TaskExists() then
  begin
    Log('AccessCam: task still present after an elevated removal attempt');
    ReportTaskRemovalFailed('');
  end
  else
    Log('AccessCam: logon task removed after elevating');
end;

procedure ReportTaskRegistrationFailed();
begin
  if WizardSilent() then
    exit;
  MsgBox('AccessCam is installed, but the task that starts it with ' +
    'administrator rights could not be registered.' +
    Chr(13) + Chr(10) + Chr(13) + Chr(10) +
    'AccessCam will still run. Without administrator rights, on-screen ' +
    'keyboards and windows running as administrator ignore the pointer ' +
    'hovering over them.' +
    Chr(13) + Chr(10) + Chr(13) + Chr(10) +
    'To fix it later: right-click AccessCam, Run as administrator, then tick ' +
    '"Start when I log in" on the Application tab.',
    mbInformation, MB_OK);
end;

procedure RegisterElevationTask();
var
  ResultCode: Integer;
  Exe: String;
begin
  Exe := ExpandConstant('{app}\AccessCam.exe');

  // AccessCam registers its own task rather than this script composing a
  // schtasks command line: one definition of what the task runs, in the place
  // that also reads it back and decides whether it is current.
  //
  // Plain attempt first - a machine-wide install is already elevated, and
  // asking twice for rights we hold would be its own small insult.
  Log('AccessCam: registering the elevated startup task');
  if Exec(Exe, '--register-task', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and
     (ResultCode = 0) then
  begin
    Log('AccessCam: startup task registered without elevating');
    exit;
  end;

  // Creating a task at /rl highest needs administrator rights. This is the
  // single prompt the design spends deliberately, here rather than at every
  // launch: see docs/RUNNING.md on why a UAC prompt is the one dialog the
  // person this is built for cannot answer.
  Log('AccessCam: asking for elevation to register the startup task');
  if not ShellExec('runas', Exe, '--register-task', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) then
  begin
    Log('AccessCam: the elevation prompt was declined or failed to launch');
    ReportTaskRegistrationFailed();
    exit;
  end;

  if ResultCode <> 0 then
  begin
    Log('AccessCam: --register-task returned ' + IntToStr(ResultCode));
    ReportTaskRegistrationFailed();
  end
  else
    Log('AccessCam: startup task registered');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // After the files are in place - it runs the installed exe - and before the
  // [Run] entry offers to launch AccessCam, so that "Launch AccessCam now"
  // already comes up elevated.
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('elevated') then
    RegisterElevationTask();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // Before the files go, in case reading the task's command ever needs them -
  // it does not today, but a check that only works by luck is worth avoiding.
  if CurUninstallStep = usUninstall then
    RemoveLogonTask();
end;
