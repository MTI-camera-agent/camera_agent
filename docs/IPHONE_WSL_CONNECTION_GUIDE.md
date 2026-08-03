# Connect HelloCamera on iPhone to the WSL test server

This guide records the end-to-end Windows Mobile Hotspot setup verified on this
machine. It uses the following path:

```text
iPhone
  ws://192.168.137.1:8766/camera
        |
        v
Windows Mobile Hotspot adapter
  192.168.137.1:8766
        |
        | Windows portproxy
        v
Windows/WSL localhost
  127.0.0.1:8765
        |
        v
WSL connection_test.py
  0.0.0.0:8765
```

Windows port `8766` and WSL port `8765` are intentionally different. On this
mirrored-networking setup, WSL already exposes its port `8765` to Windows
localhost. Trying to make Windows `portproxy` listen on the same port caused a
port collision and left the hotspot endpoint unreachable.

The instructions below assume the hotspot address is `192.168.137.1`, as
verified on this desktop. If Windows assigns a different hotspot address,
substitute it in the proxy rule, firewall rule, tests, and iPhone URL.

## 1. Enable the Windows Mobile Hotspot

On the desktop:

1. Open **Settings > Network & internet > Mobile hotspot**.
2. Turn on **Mobile hotspot**.
3. Note the network name and password.

On the iPhone:

1. Open **Settings > Wi-Fi**.
2. Select the desktop's hotspot.
3. Enter the hotspot password.
4. Confirm that the iPhone shows the Wi-Fi connection.

Keep the hotspot enabled while using HelloCamera.

## 2. Confirm the hotspot address

Open **Administrator PowerShell** and run:

```powershell
Get-NetAdapter |
  Where-Object {
    $_.InterfaceDescription -like "*Wi-Fi Direct Virtual Adapter*" -and
    $_.Status -eq "Up"
  } |
  ForEach-Object {
    Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4
  } |
  Format-Table InterfaceAlias,IPAddress,PrefixLength
```

The verified result on this desktop is:

```text
IPAddress       PrefixLength
---------       ------------
192.168.137.1   24
```

The `/24` prefix means the hotspot subnet is `192.168.137.0/24`.

## 3. Configure Windows forwarding

This is a one-time setup. The rule persists across restarts.

Still in **Administrator PowerShell**, first remove obsolete same-port proxy
rules if they exist:

```powershell
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=8765
netsh interface portproxy delete v4tov4 listenaddress=192.168.137.1 listenport=8765
```

It is harmless if Windows reports that an entry was not found.

Create the working proxy. Windows listens on hotspot port `8766` and forwards
it to the WSL service available through Windows localhost port `8765`:

```powershell
netsh interface portproxy delete v4tov4 listenaddress=192.168.137.1 listenport=8766

netsh interface portproxy add v4tov4 `
  listenaddress=192.168.137.1 listenport=8766 `
  connectaddress=127.0.0.1 connectport=8765
```

The initial delete makes the setup repeatable. It is harmless if the entry
does not exist yet.

Confirm the proxy:

```powershell
netsh interface portproxy show v4tov4
```

Expected entry:

```text
192.168.137.1   8766   127.0.0.1   8765
```

## 4. Add the Windows Firewall rule

Still in **Administrator PowerShell**, check whether the rule already exists:

```powershell
Get-NetFirewallRule -DisplayName "HelloCamera hotspot proxy" `
  -ErrorAction SilentlyContinue
```

If no rule is returned, add it:

```powershell
New-NetFirewallRule `
  -DisplayName "HelloCamera hotspot proxy" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalAddress 192.168.137.1 `
  -LocalPort 8766 `
  -RemoteAddress 192.168.137.0/24 `
  -Profile Any
```

This rule permits port `8766` only on the hotspot address and only for clients
on the hotspot subnet.

## 5. Prepare the WSL Python environment

This is a one-time setup. Open WSL and run:

```bash
cd /home/liujinyuan/Developer/agent_harness

python3 -m venv iphone_side/mock_server/.venv

iphone_side/mock_server/.venv/bin/python -m pip install \
  "websockets==15.0.1"
```

If the virtual environment already exists and imports `websockets`, this step
does not need to be repeated.

## 6. Start the WSL connection test server

Run this every time the desktop or WSL session is restarted:

```bash
cd /home/liujinyuan/Developer/agent_harness

iphone_side/mock_server/.venv/bin/python \
  iphone_side/mock_server/connection_test.py
```

Expected startup output:

```text
Listening on ws://0.0.0.0:8765/camera
Enter ws://<Windows-hotspot-IP>:8765/camera on the iPhone.
```

For this hotspot setup, do not use the printed port directly on the iPhone.
Windows exposes it externally through port `8766`.

Keep this WSL process running. Press `Ctrl+C` when testing is finished.

## 7. Verify the Windows endpoint

With the WSL server running, return to PowerShell and run:

```powershell
Test-NetConnection -ComputerName 192.168.137.1 -Port 8766
```

The important result is:

```text
TcpTestSucceeded : True
```

You can also confirm that Windows owns the listener:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8766
```

If the TCP test is false, do not troubleshoot the iPhone yet. Check that:

- `connection_test.py` is still running in WSL.
- `netsh interface portproxy show v4tov4` shows the expected entry.
- The firewall rule exists and is enabled.
- The hotspot still owns `192.168.137.1`.

## 8. Connect HelloCamera

On the iPhone:

1. Confirm it is still connected to the desktop hotspot.
2. Open HelloCamera.
3. Enter this exact endpoint:

   ```text
   ws://192.168.137.1:8766/camera
   ```

4. Tap **Connect**.
5. If iOS presents a Local Network permission prompt, tap **Allow**.
6. Leave the camera preview open.

Expected result in HelloCamera:

```text
Connection successful — the desktop received observation 1 and saved its
preview image.
```

Expected WSL output includes:

```text
[connected]
[hello] client=HelloCamera-iOS
[observation]
[saved preview]
[sent to iPhone] Connection successful ...
```

The latest received preview is written to:

```text
iphone_side/mock_server/received/latest_preview.jpg
```

The client then continues sending preview observations at approximately two
frames per second.

## Routine startup after the one-time setup

For normal use, only these steps are required:

1. Enable Windows Mobile Hotspot.
2. Connect the iPhone to that hotspot.
3. Start `connection_test.py` in WSL.
4. Confirm `Test-NetConnection 192.168.137.1 -Port 8766` succeeds if needed.
5. Connect HelloCamera to `ws://192.168.137.1:8766/camera`.

The Windows firewall and port-proxy rules persist, so they should not need to
be recreated each time.

## Troubleshooting

### HelloCamera stays on "Connecting"

Check the layers in this order:

1. **WSL server**

   ```bash
   ss -ltnp | rg ':8765'
   ```

2. **Windows proxy**

   ```powershell
   netsh interface portproxy show v4tov4
   ```

3. **Windows hotspot listener**

   ```powershell
   Test-NetConnection 192.168.137.1 -Port 8766
   ```

4. **iPhone**

   Confirm that it is connected to the hotspot and that the URL includes
   `/camera` and port `8766`.

### The proxy is listed but Windows has no listener

Check the IP Helper service:

```powershell
Get-Service iphlpsvc
```

If it must be restarted and Windows reports a running dependent service, use
the following in Administrator PowerShell:

```powershell
Stop-Service jhi_service
Restart-Service iphlpsvc
Start-Service jhi_service
```

Then check port `8766` again. This service restart was needed while diagnosing
the original same-port rule, but it should not normally be required.

### The hotspot address changed

Repeat the address check in step 2. Update all of the following to the new
address/subnet:

- The `listenaddress` in the port-proxy rule
- The firewall rule's local and remote addresses
- The PowerShell connection test
- The HelloCamera WebSocket URL

## Security note

This test uses plaintext `ws://`, so camera images, metadata, and intention text
are not encrypted. Use it only on a trusted private hotspot. Add TLS,
authentication, and pairing before distribution or use on an untrusted
network.
