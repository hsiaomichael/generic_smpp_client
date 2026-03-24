# smpp-client

A command-line SMPP 3.4 client utility for testing and debugging SMSC connections.  
Supports submitting short and long (multipart UDH) messages, delivery receipt tracking,
load testing up to 100K messages, and full PDU hex logging.

---

## Recommended names

| Item | Name |
|------|------|
| **Script** | `generic_smpp_client.py` |
| **Repository** | `smpp-client` |
| **Config file** | `smpp_client.ini` |

---

## Requirements

- Python 3.6+
- No external dependencies — standard library only

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/your-username/smpp-client.git
cd smpp-client

# 2. Create your config from the example
cp smpp_client.ini.example smpp_client.ini

# 3. Edit smpp_client.ini with your SMSC credentials and addresses
#    (smpp_client.ini is in .gitignore and will NOT be committed)

# 4. Run
python smpp_client.py
```

---

## Configuration

Settings are loaded from `smpp_client.ini` at startup.  
If the file is missing, built-in defaults are used and the startup log will say so.  
All settings can also be changed at runtime via **Menu → 5 → Edit** and are saved
back to the INI file automatically.

### INI file structure

```ini
[smsc]
server        = your.smsc.host       # SMSC hostname or IP
port          = 2775                  # SMPP port
system_id     = YOUR_SYSTEM_ID        # max 16 chars
password      = YOUR_PASSWORD         # max 9 chars
system_type   =                       # usually blank
smpp_version  = 52                    # 0x34 = SMPP 3.4

[message]
source_addr              = YOUR_SOURCE_ADDRESS
default_dest             = DESTINATION_NUMBER
request_dr               = true
default_short_text       = Test message from smpp-client
default_long_text        = Long test message...
default_ucs2_short_text  = UCS2 test message
default_ucs2_long_text   = Long UCS2 test message...

[timing]
el_interval       = 30    # enquire_link keep-alive interval (seconds)
dr_check_interval = 60    # DR audit scan interval (seconds)
resp_timeout      = 10    # submit_sm_resp wait timeout (seconds)
```

### Multiple environments

```bash
cp smpp_client.ini.example smpp_client.uat.ini   # fill with UAT values
cp smpp_client.ini.example smpp_client.prod.ini  # fill with prod values
cp smpp_client.uat.ini smpp_client.ini            # activate UAT
python smpp_client.py
```

Startup confirms which file is active:
```
[INFO] Config: Loaded: /path/to/smpp_client.ini
```

### All configuration keys

| Key | INI Section | Description |
|-----|-------------|-------------|
| `server` | `[smsc]` | SMSC hostname or IP |
| `port` | `[smsc]` | SMPP port |
| `system_id` | `[smsc]` | SMPP system ID (max 16 chars) |
| `password` | `[smsc]` | SMPP password (max 9 chars) |
| `system_type` | `[smsc]` | SMPP system type (usually blank) |
| `smpp_version` | `[smsc]` | SMPP version: 52 = 0x34 = v3.4 |
| `source_addr` | `[message]` | Source address / short code (TON=1, NPI=1) |
| `default_dest` | `[message]` | Default destination number |
| `request_dr` | `[message]` | Request delivery receipt (true/false) |
| `default_short_text` | `[message]` | Default Latin-1 short message text |
| `default_long_text` | `[message]` | Default Latin-1 long message text |
| `default_ucs2_short_text` | `[message]` | Default UCS-2 short message text |
| `default_ucs2_long_text` | `[message]` | Default UCS-2 long message text |
| `el_interval` | `[timing]` | Enquire-link interval (seconds) |
| `dr_check_interval` | `[timing]` | DR audit scan interval (seconds) |
| `resp_timeout` | `[timing]` | `submit_sm_resp` wait timeout (seconds) |

---

## Main Menu

```
==================================================
  Generic SMPP Client - Main Menu
==================================================
  1  Submit short message
  2  Submit long message (multipart)
  3  Send enquire_link manually
  4  Show pending DR status
  5  Show configuration
  0  Quit
==================================================
```

---

## Features

### 1 — Submit Short Message

Prompts for destination, encoding, and message text.  
Supports single message or **load test mode** (multiple messages at a target TPS).

**Encoding choices:**

| Choice | `data_coding` | Transport | Single SMS capacity |
|--------|--------------|-----------|---------------------|
| `1` Latin1 | `0x03` | ISO-8859-1, 1 byte/char | 140 bytes |
| `2` UCS2 | `0x08` | UTF-16 BE, 2 bytes/char | 70 chars |

**Load test mode** — triggered when count > 1:

```
  Number of messages [1]: 1000
  Target TPS (messages/sec) [10]: 100

[LT] Starting load test: 1,000 msgs @ 100.0 TPS (interval=10.0ms)
  [LT] Sent 1,000/1,000 | elapsed=10.1s | actual TPS=99.2

====================================================
  Load Test Summary
====================================================
  Messages submitted  : 1,000
  Send errors         : 0
  Resp OK             : 1,000
  Resp FAILED         : 0
  Resp timed out      : 0
  Send duration       : 10.012s
  Total duration      : 10.053s
  Avg send TPS        : 99.9
  Avg resp TPS        : 99.5
====================================================
```

- Each message has `[i/count]` appended for traceability.
- Responses collected concurrently — DRs arriving during sending are matched correctly.
- Progress printed every 5 seconds to avoid terminal flooding.
- Tested up to **100,000 messages at 100 TPS**.

### 2 — Submit Long Message (Multipart UDH)

Automatically segments messages using **Concatenated SMS UDH**
(3GPP TS 23.040 §9.2.3.24.1).

| Encoding | Single SMS | Per segment (with UDH) |
|----------|-----------|------------------------|
| Latin1 `0x03` | 140 bytes | 133 bytes + 7-byte UDH = 140 total |
| UCS2 `0x08` | 70 chars | 66 chars + 7-byte UDH = 139 bytes total |

UDH wire format:
```
UDHL=0x05 | IE_ID=0x00 | IE_LEN=0x03 | ref | total | part
```

### 3 — Send Enquire Link Manually

Sends an `enquire_link` PDU immediately.  
The background keep-alive thread also sends one automatically every `el_interval` seconds.

### 4 — Submit & DR Status

```
-- Submit & DR Status --
  Submit Statistics
    PDUs sent          : 1,000
    Resp OK  (ESME_ROK):   998
    Resp FAILED        :     2
    Resp timeout       :     0
    Resp unexpected    :     0
    Success rate       : 99.8%

  DR Tracking
    Tracked messages   :   998
    DR received        :   996  (99.80%)
    Awaiting DR        :     2
    Breakdown          : DELIVRD=994  UNDELIV=2  PENDING=2
```

Sub-menu lets you view pending, failed, or all messages with pagination (50 rows/page).

### 5 — Configuration

View and edit all settings at runtime.  
Changes are saved to `smpp_client.ini` automatically.  
Press `[R]` to reload the INI from disk without restarting.

---

## Architecture

### Threads

| Thread | Purpose |
|--------|---------|
| `main` | Interactive menu, single-message submits |
| `pdu-receiver` | Reads all incoming PDUs — routes `submit_sm_resp` to queue, handles `deliver_sm` / `enquire_link` |
| `enquire-link` | Sends keep-alive every `el_interval` seconds |
| `dr-monitor` | Periodically audits messages still awaiting DR |
| `lt-resp-collector` | Load test only — collects responses concurrently while sending |

### submit_sm_resp Routing

The `pdu-receiver` thread and `submit_sm()` both need `submit_sm_resp` PDUs.  
All `submit_sm_resp` PDUs are routed into `_submit_resp_queue`.  
`submit_sm()` reads from the queue and matches by sequence number — no race condition.

### DR Tracking

When `request_dr = true`, each successfully submitted message is registered in
`_pending_dr` keyed by `message_id`.  
When a `deliver_sm` with `esm_class & 0x04` arrives:
- DR text is parsed per SMPP 3.4 Appendix B.
- `message_id` is looked up in `_pending_dr`.
- Unknown → `WARNING: DR received for UNKNOWN message_id`.
- Duplicate → `WARNING: duplicate DR`.
- The `text:` snippet is decoded using the **original submit's** `data_coding`.

The tracking table is pruned to 200,000 entries maximum.

---

## Logging

| Destination | Level | Content |
|-------------|-------|---------|
| Console | `INFO` and above | Submits, DRs, errors, keep-alive |
| `smpp_client.log` | `DEBUG` and above | Full PDU hex dumps, every detail |

Format: `YYYY-MM-DD HH:MM:SS.microseconds [LEVEL] message`

---

## SMPP Spec Compliance

| Feature | Spec reference | Notes |
|---------|---------------|-------|
| Bind Transceiver | SMPP 3.4 §4.1.5 | Command 0x00000009 |
| Submit SM | SMPP 3.4 §4.4 | Command 0x00000004 |
| Deliver SM | SMPP 3.4 §4.6 | Full field-by-field parser |
| Enquire Link | SMPP 3.4 §4.11 | Background thread + manual |
| Unbind | SMPP 3.4 §4.1.7 | Sent on clean exit |
| Delivery Receipt | SMPP 3.4 Appendix B | Regex parser, matched by `message_id` |
| Concatenated SMS UDH | 3GPP TS 23.040 §9.2.3.24.1 | `IE_ID=0x00`, 8-bit reference |
| data_coding Latin-1 | SMPP 3.4 Table 4-9 | `0x03`, 8-bit raw |
| data_coding UCS-2 | SMPP 3.4 Table 4-9 | `0x08`, UTF-16 BE |
| Sequence numbers | SMPP 3.4 §3.2 | Thread-safe, rolls over at `0x7FFFFFFF` |
| PDU size guard | — | Rejects PDUs > 65,535 bytes |

---

## Security Notes

- `smpp_client.ini` is listed in `.gitignore` — real credentials are never committed.
- `system_id` validated to max 16 chars; `password` to max 9 chars (SMPP spec).
- TCP keepalive enabled to detect silent network drops.
- 30-second connect timeout prevents indefinite hangs.

---

## .gitignore

```
smpp_client.ini
*.log
```

---

## Repository structure

```
smpp-client/
├── smpp_client.py           # main script
├── smpp_client.ini.example  # safe template (commit this)
├── smpp_client.ini          # your real config (in .gitignore)
├── README.md
└── .gitignore
```

---

## Known Limitations

- **Bind Transceiver only** — does not support `bind_transmitter` or `bind_receiver`.
- **No auto-reconnect** — restart the script if the connection drops.
- **Source address TON/NPI** hardcoded to international (TON=1, NPI=1).
- **UCS-2 only** for Unicode — no UTF-8 or GSM7 extended table support.

---


