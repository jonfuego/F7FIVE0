; F7FIVE0 Setup (Inno Setup 6).
;
; Build with installer\build-dist.ps1, which assembles installer\dist\ and
; then runs:  ISCC /DAppVersion=1.0.0 /DAppVersionNumeric=1.0.0 F7FIVE0.iss
;
; The wizard only collects answers. installer\install.ps1 does the actual
; work (prerequisites, database, services), so a scripted install and a
; wizard install behave the same.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#ifndef AppVersionNumeric
  #define AppVersionNumeric "0.0.0"
#endif

[Setup]
; Never change AppId: upgrades find the existing install by it.
AppId={{C3BE51D0-9C50-4B20-8C7D-CC3FCE9C32FE}
AppName=F7FIVE0
AppVersion={#AppVersion}
AppVerName=F7FIVE0 {#AppVersion}
AppPublisher=F7FIVE0
VersionInfoVersion={#AppVersionNumeric}
DefaultDirName=C:\F7FIVE0
UsePreviousAppDir=yes
DirExistsWarning=no
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=Output
OutputBaseFilename=F7FIVE0-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile=dist\LICENSE
CloseApplications=no
UninstallDisplayName=F7FIVE0

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; Code folders are replaced wholesale on upgrade so removed files do not
; linger. Settings (.env), data\, and the Python venv are left alone.
Type: filesandordirs; Name: "{app}\web"
Type: filesandordirs; Name: "{app}\backend\app"
Type: filesandordirs; Name: "{app}\backend\alembic"

[INI]
Filename: "{app}\F7FIVE0.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://localhost:{code:GetPort}"

[Icons]
Name: "{autoprograms}\F7FIVE0"; Filename: "{app}\F7FIVE0.url"
Name: "{autodesktop}\F7FIVE0"; Filename: "{app}\F7FIVE0.url"; Tasks: desktopicon
Name: "{autoprograms}\F7FIVE0 logs"; Filename: "{app}\logs"
Name: "{autoprograms}\F7FIVE0 settings (.env)"; Filename: "notepad.exe"; Parameters: """{app}\.env"""

[Run]
Filename: "{app}\F7FIVE0.url"; Description: "Open F7FIVE0 in your browser"; Flags: postinstall shellexec nowait skipifsilent; Check: SetupSucceeded

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\uninstall.ps1"" -InstallDir ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveF7FIVE0Services"

[UninstallDelete]
; Runtime pieces setup downloaded. Your .env and data\ folder are kept so a
; reinstall picks up where you left off; delete them by hand to start fresh.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\backend\.venv"
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\F7FIVE0.url"

[Code]
var
  // A query page with our own Browse buttons: Inno's directory page refuses
  // blank entries, and every media folder here is optional.
  MediaPage: TInputQueryWizardPage;
  AdminPage: TInputQueryWizardPage;
  PgPage: TInputQueryWizardPage;
  NetPage: TInputOptionWizardPage;
  RemotePage: TInputOptionWizardPage;
  CfHostPage: TInputQueryWizardPage;
  OptionsPage: TInputQueryWizardPage;
  InstallFailed: Boolean;

function IsUpgrade: Boolean;
begin
  Result := FileExists(AddBackslash(WizardDirValue) + '.env');
end;

function PostgresInstalled: Boolean;
begin
  if IsWin64 then
    Result := RegKeyExists(HKLM64, 'SOFTWARE\PostgreSQL\Installations')
      or DirExists(ExpandConstant('{commonpf64}\PostgreSQL'))
  else
    Result := RegKeyExists(HKLM, 'SOFTWARE\PostgreSQL\Installations');
end;

function ReadEnvPort: String;
var
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '';
  if LoadStringsFromFile(AddBackslash(WizardDirValue) + '.env', Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
      if Pos('WEB_PORT=', Lines[I]) = 1 then
        Result := Trim(Copy(Lines[I], 10, 10));
end;

function GetPort(Param: String): String;
begin
  Result := '';
  if IsUpgrade then
    Result := ReadEnvPort;
  if (Result = '') and (OptionsPage <> nil) then
    Result := Trim(OptionsPage.Values[0]);
  if Result = '' then
    Result := '3001';
end;

function OptionalPortOk(S: String): Boolean;
var
  P: Integer;
begin
  Result := True;
  if Trim(S) <> '' then
  begin
    P := StrToIntDef(Trim(S), 0);
    Result := (P >= 1024) and (P <= 65535);
  end;
end;

function JsonEscape(S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
end;

function JsonPair(Key, Value: String; Last: Boolean): String;
begin
  Result := '  "' + Key + '": "' + JsonEscape(Value) + '"';
  if not Last then
    Result := Result + ',';
  Result := Result + #13#10;
end;

procedure BrowseMediaClick(Sender: TObject);
var
  I: Integer;
  Dir: String;
begin
  I := TNewButton(Sender).Tag;
  Dir := MediaPage.Values[I];
  if BrowseForFolder('Choose the folder F7FIVE0 should scan:', Dir, False) then
    MediaPage.Values[I] := Dir;
end;

procedure InitializeWizard;
var
  I: Integer;
  Btn: TNewButton;
begin
  MediaPage := CreateInputQueryPage(wpSelectDir,
    'Media folders', 'Where is your media?',
    'Pick the folders F7FIVE0 should scan. Leave any of them blank to skip it. ' +
    'Network paths such as \\nas\media\Movies work too.' + #13#10#13#10 +
    'Already use Radarr, Sonarr, or Lidarr? You can connect them later in the settings file.');
  MediaPage.Add('Movies:', False);
  MediaPage.Add('TV shows:', False);
  MediaPage.Add('Music:', False);
  MediaPage.Add('Music videos:', False);
  for I := 0 to 3 do
  begin
    Btn := TNewButton.Create(MediaPage);
    Btn.Parent := MediaPage.Surface;
    Btn.Caption := 'Browse...';
    Btn.Tag := I;
    Btn.Width := ScaleX(75);
    Btn.Height := MediaPage.Edits[I].Height + ScaleY(2);
    Btn.Top := MediaPage.Edits[I].Top - ScaleY(1);
    Btn.Left := MediaPage.SurfaceWidth - Btn.Width;
    Btn.Anchors := [akTop, akRight];
    Btn.OnClick := @BrowseMediaClick;
    MediaPage.Edits[I].Width := Btn.Left - ScaleX(10) - MediaPage.Edits[I].Left;
  end;

  AdminPage := CreateInputQueryPage(MediaPage.ID,
    'Admin account', 'Create your F7FIVE0 account',
    'This account runs the server and can invite everyone else.');
  AdminPage.Add('Username (lowercase letters, digits, . _ -):', False);
  AdminPage.Add('Password (8 or more characters):', True);
  AdminPage.Add('Confirm password:', True);
  AdminPage.Values[0] := 'admin';

  PgPage := CreateInputQueryPage(AdminPage.ID,
    'PostgreSQL', 'PostgreSQL is already installed on this PC',
    'F7FIVE0 stores its library in PostgreSQL. Enter the password of the "postgres" ' +
    'account so Setup can create a separate F7FIVE0 database. The password is used once and not saved.');
  PgPage.Add('postgres password:', True);

  NetPage := CreateInputOptionPage(PgPage.ID,
    'Access', 'Who can reach F7FIVE0?',
    'F7FIVE0 always works on this PC. Choose whether other devices at home can use it too.',
    False, False);
  NetPage.Add('Let phones, TVs, and other computers on my home network connect');
  NetPage.Values[0] := True;

  RemotePage := CreateInputOptionPage(NetPage.ID,
    'Listen from anywhere', 'How should you reach F7FIVE0 away from home? All options are free.',
    'TAILSCALE: no domain, no router changes. One browser sign-in (Google, Microsoft, Apple, GitHub). ' +
    'Tailscale limits Funnel bandwidth: great for music and a video stream or two, but high-bitrate ' +
    'video or several viewers at once may buffer.' + #13#10#13#10 +
    'CLOUDFLARE: no router changes, needs a domain already on Cloudflare. No bandwidth cap from ' +
    'F7FIVE0, but Cloudflare''s free-plan terms discourage heavy video streaming.' + #13#10#13#10 +
    'PORT FORWARDING (advanced): full home upload speed, no middleman. Needs router access ' +
    '(ports 80 and 443) and a domain or free DuckDNS name. Your PC is reachable directly from the internet.',
    True, False);
  RemotePage.Add('Tailscale (recommended for most people)');
  RemotePage.Add('Cloudflare (I have a domain on Cloudflare)');
  RemotePage.Add('Port forwarding (advanced: I can change my router settings)');
  RemotePage.Add('Home network only (add remote access later)');
  RemotePage.SelectedValueIndex := 0;

  CfHostPage := CreateInputQueryPage(RemotePage.ID,
    'Your address', 'Which address should F7FIVE0 use?',
    'Cloudflare: any name on a domain in your Cloudflare account (music.yourdomain.com). Setup creates ' +
    'the tunnel and DNS record.' + #13#10 +
    'Port forwarding: your own domain, or a free name from duckdns.org (myname.duckdns.org) plus its ' +
    'token so the name follows your home internet address. Setup adds HTTPS and shows the router rules.');
  CfHostPage.Add('Address (for example music.yourdomain.com):', False);
  CfHostPage.Add('DuckDNS token (port forwarding with duckdns.org only):', False);

  OptionsPage := CreateInputQueryPage(CfHostPage.ID,
    'Optional extras', 'Everything on this page can be left blank',
    'Cloudflare Tunnel token: only if you made a tunnel yourself in the Cloudflare dashboard.' + #13#10 +
    'TMDB API key (free at themoviedb.org): posters and descriptions for movies and shows.' + #13#10 +
    'Contact email: sent to MusicBrainz with music lookups, as their rules ask.');
  OptionsPage.Add('Web port:', False);
  OptionsPage.Add('Cloudflare Tunnel token (advanced):', False);
  OptionsPage.Add('TMDB API key:', False);
  OptionsPage.Add('Contact email:', False);
  OptionsPage.Add('API port (advanced, blank = 8001 or the next free port):', False);
  OptionsPage.Add('Stream port (advanced, blank = 8002 or the next free port):', False);
  OptionsPage.Values[0] := '3001';
end;

procedure CurPageChanged(CurPageID: Integer);
var
  PortForward: Boolean;
begin
  if CurPageID = CfHostPage.ID then
  begin
    PortForward := RemotePage.SelectedValueIndex = 2;
    CfHostPage.Edits[1].Visible := PortForward;
    CfHostPage.PromptLabels[1].Visible := PortForward;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if IsUpgrade and ((PageID = MediaPage.ID) or (PageID = AdminPage.ID) or (PageID = PgPage.ID)
      or (PageID = NetPage.ID) or (PageID = RemotePage.ID) or (PageID = CfHostPage.ID)
      or (PageID = OptionsPage.ID)) then
    Result := True
  else if (PageID = CfHostPage.ID) and (RemotePage.SelectedValueIndex <> 1) and (RemotePage.SelectedValueIndex <> 2) then
    Result := True
  else if (PageID = PgPage.ID) and not PostgresInstalled then
    Result := True;
end;

function ValidUsername(S: String): Boolean;
var
  I: Integer;
  C: Char;
begin
  Result := (Length(S) >= 3) and (Length(S) <= 64);
  if Result then
    for I := 1 to Length(S) do
    begin
      C := S[I];
      if not (((C >= 'a') and (C <= 'z')) or ((C >= '0') and (C <= '9')) or (C = '.') or (C = '_') or (C = '-')) then
        Result := False;
    end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Port: Integer;
begin
  Result := True;
  if CurPageID = AdminPage.ID then
  begin
    AdminPage.Values[0] := Lowercase(Trim(AdminPage.Values[0]));
    if not ValidUsername(AdminPage.Values[0]) then
    begin
      MsgBox('Usernames are 3 to 64 characters: lowercase letters, digits, dot, dash, underscore.', mbError, MB_OK);
      Result := False;
    end
    else if Length(AdminPage.Values[1]) < 8 then
    begin
      MsgBox('Please use a password of at least 8 characters.', mbError, MB_OK);
      Result := False;
    end
    else if AdminPage.Values[1] <> AdminPage.Values[2] then
    begin
      MsgBox('The passwords do not match.', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = PgPage.ID then
  begin
    if PgPage.Values[0] = '' then
    begin
      MsgBox('Enter the "postgres" password. If you do not know it, see INSTALL.md (Existing PostgreSQL).', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = CfHostPage.ID then
  begin
    CfHostPage.Values[0] := Lowercase(Trim(CfHostPage.Values[0]));
    if (Pos('.', CfHostPage.Values[0]) = 0) or (Pos('/', CfHostPage.Values[0]) > 0) or (Pos(' ', CfHostPage.Values[0]) > 0) then
    begin
      MsgBox('Enter just the address, like music.yourdomain.com (no https:// and no slashes).', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = OptionsPage.ID then
  begin
    Port := StrToIntDef(Trim(OptionsPage.Values[0]), 0);
    if (Port < 1024) or (Port > 65535) then
    begin
      MsgBox('Pick a web port between 1024 and 65535 (3001 is fine).', mbError, MB_OK);
      Result := False;
    end
    else if not OptionalPortOk(OptionsPage.Values[4]) or not OptionalPortOk(OptionsPage.Values[5]) then
    begin
      MsgBox('API and stream ports are optional. If you fill one in, use a number between 1024 and 65535.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  // Stop running services so their files can be replaced on upgrade.
  Exec(ExpandConstant('{sys}\net.exe'), 'stop F7FIVE0-Web', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\net.exe'), 'stop F7FIVE0-Stream', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\net.exe'), 'stop F7FIVE0-API', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Cfg, CfgPath, Params, Lan, Remote: String;
  ResultCode: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;

  CfgPath := ExpandConstant('{tmp}\f7five0-setup.json');
  if NetPage.Values[0] then Lan := '1' else Lan := '0';
  case RemotePage.SelectedValueIndex of
    0: Remote := 'tailscale';
    1: Remote := 'cloudflare';
    2: Remote := 'portforward';
  else
    Remote := 'none';
  end;
  Cfg := '{' + #13#10;
  if not IsUpgrade then
  begin
    Cfg := Cfg +
      JsonPair('adminUser', AdminPage.Values[0], False) +
      JsonPair('adminPassword', AdminPage.Values[1], False) +
      JsonPair('postgresPassword', PgPage.Values[0], False) +
      JsonPair('moviesDir', MediaPage.Values[0], False) +
      JsonPair('tvDir', MediaPage.Values[1], False) +
      JsonPair('musicDir', MediaPage.Values[2], False) +
      JsonPair('musicVideosDir', MediaPage.Values[3], False) +
      JsonPair('openFirewall', Lan, False) +
      JsonPair('webPort', Trim(OptionsPage.Values[0]), False) +
      JsonPair('apiPort', Trim(OptionsPage.Values[4]), False) +
      JsonPair('streamPort', Trim(OptionsPage.Values[5]), False) +
      JsonPair('tunnelToken', Trim(OptionsPage.Values[1]), False) +
      JsonPair('tmdbKey', Trim(OptionsPage.Values[2]), False) +
      JsonPair('remoteAccess', Remote, False) +
      JsonPair('publicHost', CfHostPage.Values[0], False) +
      JsonPair('duckDnsToken', Trim(CfHostPage.Values[1]), False);
  end;
  Cfg := Cfg + JsonPair('contactEmail', Trim(OptionsPage.Values[3]), True) + '}';
  SaveStringToFile(CfgPath, Cfg, False);

  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\installer\install.ps1') +
    '" -InstallDir "' + ExpandConstant('{app}') + '" -ConfigFile "' + CfgPath + '" -NonInteractive';
  WizardForm.StatusLabel.Caption := 'Setting up F7FIVE0. A console window shows progress; this can take 10 minutes on a new PC...';
  if not Exec('powershell.exe', Params, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
  begin
    InstallFailed := True;
    MsgBox('F7FIVE0 setup did not finish (code ' + IntToStr(ResultCode) + ').' + #13#10#13#10 +
      'The log is in ' + ExpandConstant('{app}\logs') + '. Fix the problem it names and run Setup again; ' +
      'it picks up where it stopped.', mbError, MB_OK);
  end;
  DeleteFile(CfgPath);
end;

function SetupSucceeded: Boolean;
begin
  Result := not InstallFailed;
end;
