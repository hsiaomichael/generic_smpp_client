import socket
import re
import struct
import time
import threading
import select
import queue
import logging
import os
import configparser
import sys

# ---------------------------------------------------------------------------
# Configuration  (mutable at runtime via menu option 5 -> Edit)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Default configuration values (overridden by smpp_client.ini if present)
# ---------------------------------------------------------------------------
_CFG_DEFAULTS = {
    # Connection -- replace with values from smpp_client.ini
    'server':             'localhost',
    'port':               '2775',
    'system_id':          'YOUR_SYSTEM_ID',
    'password':           'YOUR_PASS',
    'system_type':        '',
    'source_addr':        'YOUR_SOURCE',
    'smpp_version':       '52',          # 0x34 = SMPP 3.4
    'el_interval':        '30',
    'dr_check_interval':  '60',
    'resp_timeout':       '10',
    'default_dest':       'DESTINATION',
    'request_dr':         'true',
    'default_short_text': 'Test message from generic_smpp_client',
    'default_long_text': (
        'SEG1 This is segment 1 of the GSM/SMPP long message. It continues '
        'the structured transmission, ensuring clarity and coherence '
        'throughout. Segment 1 provi'
        'SEG2 This is segment 2 of the GSM/SMPP long message. It continues '
        'the structured transmission, ensuring clarity and coherence '
        'throughout. Segment 2 provi'
        'SEG3 This is segment 3 of the GSM/SMPP long message. It continues '
        'the structured transmission, ensuring clarity and coherence '
        'throughout. Segment 3 provi'
    ),
    'default_ucs2_short_text': (
        u'A2P 簡訊服務 SMS；有時也稱為'
        u'訊息、簡訊、文字訊息'
    ),
    'default_ucs2_long_text': (
        u'當一則簡訊（SMS）超過標準'
        u'長度限制時（例如 GSM 7-bit 編碼'
        u'的 160 字元或 UCS-2 編碼的 70 字元'
        u'），GSM 系統會使用（Concatenated SMS'
        u'） 技術來分割並傳送訊息'
        u'。每一部分都會附加一段'
        u'特殊的資料，稱為（UDH） UDH '
        u'是一段佔用空間的控制資'
        u'訊，通常佔用 6 或 7 個位元'
        u'組（bytes）。因此每一部分'
        u'可用的字元數會比單一 SMS 少'
        u'： GSM 7-bit 編碼：每段最多 153 字'
        u'元 UCS-2 編碼：每段最多 67 字元'
    ),
}

INI_FILE = 'smpp_client.ini'

def _load_ini():
    """
    Load configuration from INI file, falling back to _CFG_DEFAULTS.
    The INI file is UTF-8 encoded to support Unicode default texts.
    Returns the CFG dict with correctly typed values.
    """
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(INI_FILE, encoding='utf-8')

    def get(section, key, fallback):
        try:
            return cp.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    return {
        # [smsc] section
        'server':        get('smsc', 'server',      _CFG_DEFAULTS['server']),
        'port':          int(get('smsc', 'port',    _CFG_DEFAULTS['port'])),
        'system_id':     get('smsc', 'system_id',   _CFG_DEFAULTS['system_id']),
        'password':      get('smsc', 'password',    _CFG_DEFAULTS['password']),
        'system_type':   get('smsc', 'system_type', _CFG_DEFAULTS['system_type']),
        'smpp_version':  int(get('smsc', 'smpp_version', _CFG_DEFAULTS['smpp_version'])),

        # [message] section
        'source_addr':   get('message', 'source_addr',   _CFG_DEFAULTS['source_addr']),
        'default_dest':  get('message', 'default_dest',  _CFG_DEFAULTS['default_dest']),
        'request_dr':    get('message', 'request_dr',    _CFG_DEFAULTS['request_dr']).lower()
                         in ('true', '1', 'yes'),
        'default_short_text': get('message', 'default_short_text',
                                  _CFG_DEFAULTS['default_short_text']),
        'default_long_text':  get('message', 'default_long_text',
                                  _CFG_DEFAULTS['default_long_text']),
        'default_ucs2_short_text': get('message', 'default_ucs2_short_text',
                                       _CFG_DEFAULTS['default_ucs2_short_text']),
        'default_ucs2_long_text':  get('message', 'default_ucs2_long_text',
                                       _CFG_DEFAULTS['default_ucs2_long_text']),

        # [timing] section
        'el_interval':       int(get('timing', 'el_interval',
                                     _CFG_DEFAULTS['el_interval'])),
        'dr_check_interval': int(get('timing', 'dr_check_interval',
                                     _CFG_DEFAULTS['dr_check_interval'])),
        'resp_timeout':      int(get('timing', 'resp_timeout',
                                     _CFG_DEFAULTS['resp_timeout'])),
    }

CFG = _load_ini()


def _save_ini():
    """
    Write current CFG back to smpp_client.ini so runtime edits persist.
    Creates the file if it does not exist.
    """
    cp = configparser.ConfigParser(interpolation=None)

    cp['smsc'] = {
        'server':       CFG['server'],
        'port':         str(CFG['port']),
        'system_id':    CFG['system_id'],
        'password':     CFG['password'],
        'system_type':  CFG['system_type'],
        'smpp_version': str(CFG['smpp_version']),
    }
    cp['message'] = {
        'source_addr':             CFG['source_addr'],
        'default_dest':            CFG['default_dest'],
        'request_dr':              'true' if CFG['request_dr'] else 'false',
        'default_short_text':      CFG['default_short_text'],
        'default_long_text':       CFG['default_long_text'],
        'default_ucs2_short_text': CFG['default_ucs2_short_text'],
        'default_ucs2_long_text':  CFG['default_ucs2_long_text'],
    }
    cp['timing'] = {
        'el_interval':       str(CFG['el_interval']),
        'dr_check_interval': str(CFG['dr_check_interval']),
        'resp_timeout':      str(CFG['resp_timeout']),
    }

    try:
        with open(INI_FILE, 'w', encoding='utf-8') as f:
            cp.write(f)
        return True
    except OSError as e:
        print(f"[ERROR] Could not save {INI_FILE}: {e}")
        return False

# ---------------------------------------------------------------------------
# Logger  (console + file, microsecond timestamps)
# ---------------------------------------------------------------------------
LOG_FILE = 'generic_submit_sm.log'

def _setup_logger():
    fmt = logging.Formatter(
        fmt='%(asctime)s.%(msecs)06d [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Patch asctime to include microseconds via a filter
    class _UsecFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            import datetime
            ct = datetime.datetime.fromtimestamp(record.created)
            if datefmt:
                s = ct.strftime(datefmt)
            else:
                s = ct.strftime('%Y-%m-%d %H:%M:%S')
            return f"{s}.{ct.microsecond:06d}"

    fmt2 = _UsecFormatter(
        fmt='%(asctime)s [%(levelname)s] %(message)s'
    )
    log = logging.getLogger('smpp')
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        # Console: INFO+ only (no hex dump noise)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt2)
        log.addHandler(ch)
        # File: DEBUG+ (full hex dumps, every detail)
        fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt2)
        log.addHandler(fh)
    return log

logger = _setup_logger()

def log(level, msg):
    """Convenience: log at given level and also ensure it goes to console."""
    getattr(logger, level)(msg)

# ---------------------------------------------------------------------------
# SMPP constants
# ---------------------------------------------------------------------------
BIND_TRANSCEIVER      = 0x00000009
BIND_TRANSCEIVER_RESP = 0x80000009
UNBIND                = 0x00000006
UNBIND_RESP           = 0x80000006
SUBMIT_SM             = 0x00000004
SUBMIT_SM_RESP        = 0x80000004
DELIVER_SM            = 0x00000005
DELIVER_SM_RESP       = 0x80000005
ENQUIRE_LINK          = 0x00000015
ENQUIRE_LINK_RESP     = 0x80000015
ESME_ROK              = 0x00000000

ESM_CLASS_DELIVERY_RECEIPT = 0x04

# Encoding constants
# data_coding values (SMPP spec Table 4-9)
# Only Latin-1 (0x03) and UCS2 (0x08) are supported. Both use 8-bit raw transport.
DATA_CODING_LATIN1 = 0x03   # ISO-8859-1 / Latin-1  -- 1 byte/char
DATA_CODING_UCS2   = 0x08   # UCS-2 (UTF-16 BE)     -- 2 bytes/char

# Capacity limits (PDU body hard limit = 140 bytes)
LATIN1_MAX_BYTES      = 140   # single SMS  (140 chars)
LATIN1_UDH_MAX_BYTES  = 133   # per part    (7-byte UDH + 133 bytes = 140)
UCS2_MAX_BYTES        = 140   # single SMS  (70 chars x 2 = 140 bytes)
UCS2_UDH_MAX_BYTES    = 132   # per part    (66 chars x 2 = 132 + 7 UDH = 139)

STATUS_CODES = {
    ESME_ROK:   "OK",
    0x00000001: "Message Length is invalid",
    0x00000002: "Command Length is invalid",
    0x00000003: "Invalid Command ID",
    0x00000004: "Incorrect BIND status for given command",
    0x00000005: "ESME Already in Bound State",
    0x00000006: "Invalid Priority Flag",
    0x00000007: "Invalid Registered Delivery Flag",
    0x00000008: "System Error",
    0x0000000A: "Invalid Source Address",
    0x0000000B: "Invalid Destination Address",
    0x0000000C: "Message ID is invalid",
    0x0000000D: "Bind Failed",
    0x0000000E: "Invalid Password",
    0x0000000F: "Invalid System ID",
    0x00000011: "Cancel SM Failed",
    0x00000013: "Replace SM Failed",
    0x00000014: "Message Queue Full",
    0x00000015: "Invalid Service Type",
    0x00000033: "Invalid number of destinations",
    0x00000034: "Invalid Distribution List name",
    0x00000040: "Destination flag is invalid (submit_multi)",
    0x00000042: "Invalid 'submit with replace' request",
    0x00000043: "Invalid esm_class field data",
    0x00000044: "Cannot Submit to Distribution List",
    0x00000045: "submit_sm or submit_multi failed",
    0x00000048: "Invalid Source address TON",
    0x00000049: "Invalid Source address NPI",
    0x00000050: "Invalid Destination address TON",
    0x00000051: "Invalid Destination address NPI",
    0x00000053: "Invalid system_type field",
    0x00000054: "Invalid replace_if_present flag",
    0x00000055: "Invalid number of messages",
    0x00000058: "Throttling error (ESME has exceeded allowed message limits)",
    0x00000061: "Invalid Scheduled Delivery Time",
    0x00000062: "Invalid message validity period (Expiry time)",
    0x00000063: "Predefined Message Invalid or Not Found",
    0x00000064: "ESME Receiver Temporary App Error Code",
    0x00000065: "ESME Receiver Permanent App Error Code",
    0x00000066: "ESME Receiver Reject Message Error Code",
    0x00000067: "query_sm request failed",
    0x000000C0: "Error in the optional part of the PDU Body.",
    0x000000C1: "Optional Parameter not allowed",
    0x000000C2: "Invalid Parameter Length.",
    0x000000C3: "Expected Optional Parameter missing",
    0x000000C4: "Invalid Optional Parameter Value",
    0x000000FE: "Delivery Failure (data_sm_resp)",
    0x000000FF: "Unknown Error",
}

DR_STATUS_MAP = {
    'DELIVRD': 'Delivered',
    'EXPIRED': 'Expired',
    'DELETED': 'Deleted',
    'UNDELIV': 'Undeliverable',
    'ACCEPTD': 'Accepted',
    'UNKNOWN': 'Unknown',
    'REJECTD': 'Rejected',
    'ENROUTE': 'En route (still trying)',
}

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

# DR tracking table:
#   message_id (str) -> {'dest', 'text', 'submitted_at', 'dr_received', 'dr_stat'}
_pending_dr      = {}
_pending_dr_lock = threading.Lock()

# Submit outcome counters (cumulative across the whole session)
_submit_stats = {
    'sent':      0,   # PDUs handed to send_pdu() without exception
    'ok':        0,   # submit_sm_resp with ESME_ROK received
    'failed':    0,   # submit_sm_resp with error status received
    'timeout':   0,   # no resp received within resp_timeout
    'unexpected':0,   # resp PDU with wrong command_id
}
_submit_stats_lock = threading.Lock()

def _stat(key, n=1):
    """Increment a submit stats counter thread-safely."""
    with _submit_stats_lock:
        _submit_stats[key] += n

# Thread-safe sequence counter
_seq_lock        = threading.Lock()
_sequence_number = 1

# Socket write lock (main thread + enquire-link thread share the socket)
_sock_lock       = threading.Lock()

# ---------------------------------------------------------------------------
# submit_sm_resp routing
#
# Problem: both the main thread (waiting for submit_sm_resp after sending
# submit_sm) and the pdu-receiver thread read from the same socket.
# If the receiver thread grabs the submit_sm_resp first, the main thread
# starves and reports a failure even though the SMSC accepted the message.
#
# Solution: the receiver thread puts every SUBMIT_SM_RESP it sees into
# this queue. submit_sm() reads the response from the queue instead of
# directly from the socket, so there is no race.
# ---------------------------------------------------------------------------
_submit_resp_queue = queue.Queue()

# ---------------------------------------------------------------------------
# Helpers: sequence number, socket I/O
# ---------------------------------------------------------------------------

def next_sequence():
    global _sequence_number
    with _seq_lock:
        seq = _sequence_number
        _sequence_number = (_sequence_number % 0x7FFFFFFF) + 1
    return seq


def send_pdu(sock, pdu):
    with _sock_lock:
        try:
            _hex_dump(pdu, 'TX')
            sock.sendall(pdu)
        except Exception as e:
            log("error", f"[ERROR] send_pdu: {e}")
            raise


def recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise IOError("Connection closed prematurely")
        buf += chunk
    return buf


MAX_PDU_SIZE = 65535  # SMPP max is well under 64KB; guard against malformed/malicious PDUs

def read_pdu(sock):
    header = recv_exact(sock, 16)
    command_length, = struct.unpack_from('>I', header, 0)
    if command_length < 16:
        raise IOError(f"Malformed PDU: command_length={command_length} (too small)")
    if command_length > MAX_PDU_SIZE:
        raise IOError(f"Malformed PDU: command_length={command_length} exceeds MAX_PDU_SIZE={MAX_PDU_SIZE}")
    body = recv_exact(sock, command_length - 16)
    pdu = header + body
    _hex_dump(pdu, 'RX')
    return pdu


def parse_header(pdu):
    return struct.unpack('>IIII', pdu[:16])


def _hex_dump(pdu, label):
    """DEBUG level -> file only. Console shows INFO+ only (no hex noise)."""
    _, cmd_id, cmd_status, seq = struct.unpack_from('>IIII', pdu)
    hex_str = ' '.join(f'{b:02X}' for b in pdu)
    log('debug', f"[PDU-HEX] {label} cmd=0x{cmd_id:08X} seq={seq} "        f"status=0x{cmd_status:08X} len={len(pdu)}")
    log('debug', f"[PDU-HEX] bytes: {hex_str}")



# ---------------------------------------------------------------------------
# PDU decoders
# ---------------------------------------------------------------------------

def decode_bind_transceiver_resp(pdu):
    _, command_id, command_status, seq = parse_header(pdu)
    system_id = pdu[16:].split(b'\x00', 1)[0].decode('ascii', errors='replace')
    return command_id, command_status, seq, system_id


def decode_submit_sm_resp(pdu):
    _, command_id, command_status, seq = parse_header(pdu)
    message_id = pdu[16:].split(b'\x00', 1)[0].decode('ascii', errors='replace')
    return command_id, command_status, seq, message_id


def decode_deliver_sm(pdu):
    """
    Full field-by-field parser for deliver_sm body (SMPP 3.4 section 4.6.1).
    Returns (command_id, command_status, seq, esm_class,
             source_addr, dest_addr, data_coding, short_message)
    """
    _, command_id, command_status, seq = parse_header(pdu)
    body = pdu[16:]
    pos  = 0

    def read_cstr():
        nonlocal pos
        end = body.index(b'\x00', pos)
        val = body[pos:end].decode('ascii', errors='replace')
        pos = end + 1
        return val

    def read_byte():
        nonlocal pos
        if pos >= len(body):
            raise IOError(f"Truncated deliver_sm body at offset {pos}")
        val = body[pos]
        pos += 1
        return val

    _service_type       = read_cstr()
    _src_ton            = read_byte()
    _src_npi            = read_byte()
    source_addr         = read_cstr()
    _dst_ton            = read_byte()
    _dst_npi            = read_byte()
    dest_addr           = read_cstr()
    esm_class           = read_byte()
    _protocol_id        = read_byte()
    _priority_flag      = read_byte()
    _sched_delivery     = read_cstr()
    _validity_period    = read_cstr()
    _reg_delivery       = read_byte()
    _replace_if_present = read_byte()
    data_coding         = read_byte()
    _sm_default_msg_id  = read_byte()
    sm_length           = read_byte()
    # Return raw bytes -- caller must decode based on data_coding.
    # Do NOT decode as ascii here: packed GSM7 bytes > 0x7F would be
    # silently replaced with '?' destroying the content.
    short_message_bytes = body[pos:pos + sm_length]

    return (command_id, command_status, seq, esm_class,
            source_addr, dest_addr, data_coding, short_message_bytes)

# ---------------------------------------------------------------------------
# DR tracking
# ---------------------------------------------------------------------------

def register_submitted_message(message_id, dest_addr, text, data_coding=DATA_CODING_LATIN1):
    """Record a successfully submitted message so we can track its DR."""
    with _pending_dr_lock:
        _pending_dr[message_id] = {
            'dest':         dest_addr,
            'text':         text,
            'data_coding':  data_coding,
            'submitted_at': time.time(),
            'dr_received':  False,
            'dr_stat':      None,
        }
    log("debug", f"[TRACK] Registered message_id={message_id!r} dest={dest_addr}")


def parse_delivery_receipt(text):
    """
    Parse standard SMPP delivery receipt text (SMPP 3.4 Appendix B).
    Returns dict or None if not recognised.
    """
    pattern = (
        r'id:(\S+)\s+'
        r'sub:(\d+)\s+'
        r'dlvrd:(\d+)\s+'
        r'submit date:(\d+)\s+'
        r'done date:(\d+)\s+'
        r'stat:(\w+)\s+'
        r'err:(\w+)'
        r'(?:\s+text:(.*))?'
    )
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    stat = m.group(6).upper()
    # text: field is raw bytes embedded in a latin-1 decoded string.
    # Re-encode as latin-1 to recover the original bytes for proper decoding.
    raw_text_str = (m.group(8) or '').strip()
    text_bytes   = raw_text_str.encode('latin-1', errors='replace')
    return {
        'msg_id':      m.group(1),
        'sub':         m.group(2),
        'dlvrd':       m.group(3),
        'submit_date': m.group(4),
        'done_date':   m.group(5),
        'stat':        stat,
        'stat_desc':   DR_STATUS_MAP.get(stat, 'Unknown status'),
        'err':         m.group(7),
        'text':        text_bytes,   # raw bytes, decoded later by decode_dr_text()
    }


def process_delivery_receipt(seq, short_message, pdu_data_coding=None):
    """
    Match an incoming DR against the pending-DR table.
    Warns if the message_id is unknown or a duplicate arrives.

    short_message    : raw bytes of the DR PDU's short_message field
    pdu_data_coding  : data_coding from the DR PDU itself (informational only;
                       we use the STORED original submit data_coding for text decoding)
    """
    # Decode the DR PDU body as latin-1 to make the ascii fields readable
    # while preserving all byte values in the text: field
    if isinstance(short_message, bytes):
        short_message_str = short_message.decode('latin-1', errors='replace')
    else:
        short_message_str = short_message
    dr = parse_delivery_receipt(short_message_str)
    if not dr:
        log("warning", f"[DR] seq={seq} WARNING: non-standard DR format | "
              f"raw={short_message!r}")
        return

    msg_id = dr['msg_id']
    stat   = dr['stat']
    desc   = dr['stat_desc']

    with _pending_dr_lock:
        entry = _pending_dr.get(msg_id)

        if entry is None:
            log("warning", f"[DR] WARNING: DR received for UNKNOWN message_id={msg_id!r}")
            log("warning", f"     stat={stat} ({desc}) | err={dr['err']} | "
                  f"raw={short_message!r}")
            return

        if entry['dr_received']:
            log("warning", f"[DR] WARNING: duplicate DR for message_id={msg_id!r} | "
                  f"prev_stat={entry['dr_stat']} | new_stat={stat}")
        else:
            entry['dr_received'] = True
            entry['dr_stat']     = stat

    elapsed     = time.time() - entry['submitted_at']
    dc          = entry.get('data_coding', DATA_CODING_LATIN1)
    pdu_dc_str = f"0x{pdu_data_coding:02X}" if pdu_data_coding is not None else "??"
    log('debug', f"[DR] Decoding text: field using stored dc=0x{dc:02X} "
        f"(DR PDU dc={pdu_dc_str}) "
        f"raw_bytes={dr['text'].hex() if dr['text'] else ''}")
    decoded_txt = decode_dr_text(dr['text'], dc)
    log("info", f"[DR] message_id={msg_id!r} | stat={stat} ({desc}) | "
          f"err={dr['err']} | elapsed={elapsed:.1f}s | "
          f"submit={dr['submit_date']} | done={dr['done_date']} | "
          f"dest={entry['dest']} | text={decoded_txt!r}")


# Max entries to keep in _pending_dr before pruning oldest completed ones
_PENDING_DR_MAX = 200_000  # supports 100K+ load tests with DR tracking

def _prune_pending_dr():
    """Remove oldest DR-received entries if table exceeds _PENDING_DR_MAX."""
    with _pending_dr_lock:
        if len(_pending_dr) <= _PENDING_DR_MAX:
            return
        # Sort by submitted_at, remove oldest completed entries first
        completed = sorted(
            [(mid, e) for mid, e in _pending_dr.items() if e['dr_received']],
            key=lambda x: x[1]['submitted_at']
        )
        to_remove = len(_pending_dr) - _PENDING_DR_MAX
        for mid, _ in completed[:to_remove]:
            del _pending_dr[mid]
        if to_remove > 0:
            log('debug', f"[DR] Pruned {to_remove} completed DR entries from tracking table")


def check_pending_dr():
    """Print messages that have not yet received a DR."""
    _prune_pending_dr()
    now = time.time()
    with _pending_dr_lock:
        pending = [(mid, e) for mid, e in _pending_dr.items()
                   if not e['dr_received']]
    if not pending:
        return
    log("warning", f"[DR-AUDIT] {len(pending)} message(s) still awaiting DR:")
    for mid, e in pending:
        age = now - e['submitted_at']
        log("warning", f"  message_id={mid!r} dest={e['dest']} "
              f"age={age:.0f}s text={e['text'][:40]!r}")

# ---------------------------------------------------------------------------
# SMPP operations
# ---------------------------------------------------------------------------

def bind_transceiver(sock):
    seq  = next_sequence()
    body = (CFG['system_id'].encode('ascii')   + b'\x00' +
            CFG['password'].encode('ascii')    + b'\x00' +
            CFG['system_type'].encode('ascii') + b'\x00' +
            struct.pack('B', CFG['smpp_version']) +
            struct.pack('B', 0x00) +   # addr_ton
            struct.pack('B', 0x00) +   # addr_npi
            b'\x00')                   # address_range
    cmd_len = 16 + len(body)
    send_pdu(sock, struct.pack('>IIII', cmd_len, BIND_TRANSCEIVER, 0, seq) + body)
    pdu = read_pdu(sock)
    command_id, command_status, _, system_id = decode_bind_transceiver_resp(pdu)
    if command_id == BIND_TRANSCEIVER_RESP and command_status == ESME_ROK:
        log("info", f"[BIND] Transceiver bound OK: system_id={system_id!r}")
        return True
    status_msg = STATUS_CODES.get(command_status, "Unknown status")
    log("error", f"[BIND] Failed: 0x{command_status:08X} ({status_msg})")
    return False


def _build_submit_sm_pdu(source_addr, dest_addr, message_bytes,
                          esm_class=0x00, data_coding=DATA_CODING_LATIN1,
                          ref_num=0, total_parts=1, part_num=1,
                          request_dr=True):
    """
    Build one submit_sm PDU.

    message_bytes : encoded bytes (iso-8859-1 for Latin1, utf-16-be for UCS2)
    data_coding   : DATA_CODING_LATIN1 (0x03) | DATA_CODING_UCS2 (0x08)
    request_dr    : True  -> registered_delivery=0x01 (SMSC sends delivery receipt)
                    False -> registered_delivery=0x00 (no DR expected)

    sm_length rules (both encodings use 8-bit raw transport):
      Single SMS  : byte count of message_bytes
      Multipart   : byte count of (UDHL + UDH_IE + message_bytes)
    """
    seq = next_sequence()

    if total_parts > 1:
        # Concatenated SMS UDH (3GPP TS 23.040 s9.2.3.24.1)
        # Wire: UDHL | IE_ID | IE_LEN | ref | total | part
        #       0x05   0x00    0x03    ...   ...    ...
        #   UDHL  = 0x05 : 5 UDH bytes follow (not counting UDHL itself)
        #   IE_ID = 0x00 : Concatenated Short Message, 8-bit reference
        #   IE_LEN= 0x03 : 3 bytes of IE payload follow
        udh_ie    = bytes([0x00, 0x03, ref_num & 0xFF, total_parts, part_num])
        udhl      = bytes([len(udh_ie)])   # = 0x05
        payload   = udhl + udh_ie + message_bytes
        esm_class = 0x40               # UDH indicator
        sm_length = len(payload)       # total byte count including UDH
    else:
        payload   = message_bytes
        sm_length = len(payload)   # Latin1 and UCS2: sm_length = byte count

    body = (b'\x00' +
            struct.pack('B', 0x01) +                 # source_addr_ton
            struct.pack('B', 0x01) +                 # source_addr_npi
            source_addr.encode('ascii') + b'\x00' +
            struct.pack('B', 0x01) +                 # dest_addr_ton
            struct.pack('B', 0x01) +                 # dest_addr_npi
            dest_addr.encode('ascii') + b'\x00' +
            struct.pack('B', esm_class) +
            struct.pack('B', 0x00) +                 # protocol_id
            struct.pack('B', 0x00) +                 # priority_flag
            b'\x00' +                                # schedule_delivery_time
            b'\x00' +                                # validity_period
            struct.pack('B', 0x01 if request_dr else 0x00) +  # registered_delivery
            struct.pack('B', 0x00) +                 # replace_if_present
            struct.pack('B', data_coding) +
            struct.pack('B', 0x00) +                 # sm_default_msg_id
            struct.pack('B', sm_length) +
            payload)

    cmd_len = 16 + len(body)
    return seq, struct.pack('>IIII', cmd_len, SUBMIT_SM, 0, seq) + body


def _wait_submit_resp(seq):
    """
    Wait for a submit_sm_resp that matches our sequence number.
    Responses are placed in _submit_resp_queue by the pdu-receiver thread.
    Any responses for other sequences are re-queued (handles pipelining).
    """
    deadline = time.time() + CFG['resp_timeout']
    stash    = []

    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            # Put stashed items back so nothing is lost
            for item in stash:
                _submit_resp_queue.put(item)
            raise TimeoutError(
                f"Timed out waiting for submit_sm_resp seq={seq}")
        try:
            pdu = _submit_resp_queue.get(timeout=min(remaining, 1.0))
        except queue.Empty:
            continue

        _, cmd_id, cmd_status, resp_seq = parse_header(pdu)
        if resp_seq == seq:
            # Put stashed items back before returning
            for item in stash:
                _submit_resp_queue.put(item)
            return pdu
        else:
            # Not ours - stash it and keep waiting
            stash.append(pdu)




def _decode_sm_bytes(raw_bytes, data_coding):
    """
    Decode deliver_sm short_message bytes using the PDU's own data_coding.
    Used for MO messages and as a building block for DR text decoding.
    """
    try:
        if data_coding == DATA_CODING_UCS2:
            if len(raw_bytes) % 2:
                raw_bytes += b'\x00'
            return raw_bytes.decode('utf-16-be', errors='replace')
        elif data_coding == DATA_CODING_LATIN1:
            return raw_bytes.decode('iso-8859-1', errors='replace')
        else:
            # GSM7 or unknown: treat as ASCII-safe latin-1 for printable range
            return raw_bytes.decode('latin-1', errors='replace')
    except Exception:
        return repr(raw_bytes)


def decode_dr_text(raw_bytes, data_coding):
    """
    Decode the text: snippet from a delivery receipt.

    The SMSC copies the first ~20 chars of the original message into the
    DR text: field using the ORIGINAL submit's data_coding -- not the DR
    PDU's own data_coding (which is typically 0x03 Latin1 for the wrapper).

    raw_bytes   : the bytes after 'text:' in the DR short_message
    data_coding : the ORIGINAL submit's data_coding (from _pending_dr table)

    0x03 Latin1: raw ISO-8859-1 bytes
    0x08 UCS2  : raw UTF-16 BE bytes
    """
    if not raw_bytes:
        return ''
    try:
        if data_coding == DATA_CODING_UCS2:
            if len(raw_bytes) % 2:
                raw_bytes += b'\x00'
            return raw_bytes.decode('utf-16-be', errors='replace')
        elif data_coding == DATA_CODING_LATIN1:
            return raw_bytes.decode('iso-8859-1', errors='replace')
        else:
            # Latin1: raw ISO-8859-1
            return raw_bytes.decode('iso-8859-1', errors='replace')
    except Exception:
        return repr(raw_bytes)


def _encode_message(text, data_coding):
    """
    Encode text according to data_coding.
    Returns (encoded_bytes, label, char_count).

    0x03 Latin1: ISO-8859-1 raw bytes, 1 byte/char  -- sm_length = byte count
    0x08 UCS2  : UTF-16 BE raw bytes,  2 bytes/char -- sm_length = byte count
    """
    if data_coding == DATA_CODING_UCS2:
        encoded = text.encode('utf-16-be')
        label   = 'UCS2(0x08)'
    elif data_coding == DATA_CODING_LATIN1:
        encoded = text.encode('iso-8859-1', errors='replace')
        label   = 'Latin1(0x03)'
    else:
        # Default: GSM7 7-bit packed
        encoded = text.encode('iso-8859-1', errors='replace')
        label   = 'Latin1(0x03)'
    return encoded, label, len(text)


def submit_sm(sock, dest_addr, message_text, data_coding=DATA_CODING_LATIN1,
              request_dr=None):
    """
    Submit a single short message.
    data_coding: DATA_CODING_LATIN1 (0x03) | DATA_CODING_UCS2 (0x08)
    request_dr : True/False or None to use CFG['request_dr']
    """
    message_bytes, enc_label, char_count = _encode_message(message_text, data_coding)

    # Capacity warning
    if data_coding == DATA_CODING_UCS2:
        max_ch = UCS2_MAX_BYTES // 2
        if char_count > max_ch:
            log("warning", f"[WARN] {enc_label}: {char_count} chars (max {max_ch}); "
                f"use option 2 for long messages.")
    else:
        if len(message_bytes) > LATIN1_MAX_BYTES:
            log("warning", f"[WARN] {enc_label}: {len(message_bytes)} bytes "
                f"(max {LATIN1_MAX_BYTES}); use option 2 for long messages.")

    dr = CFG['request_dr'] if request_dr is None else request_dr
    seq, pdu = _build_submit_sm_pdu(CFG['source_addr'], dest_addr,
                                     message_bytes, data_coding=data_coding,
                                     request_dr=dr)
    dr_label = 'DR' if dr else 'no-DR'
    log('info',  f"[TX] submit_sm seq={seq} {enc_label} {char_count} chars / "
        f"{len(message_bytes)} bytes {dr_label} -> {dest_addr}")
    log('debug', f"[SUBMIT] detail: dc=0x{data_coding:02X} "        f"chars={char_count} payload_bytes={len(message_bytes)} request_dr={dr}")
    send_pdu(sock, pdu)
    _stat('sent')

    try:
        resp = _wait_submit_resp(seq)
    except TimeoutError as e:
        _stat('timeout')
        log("warning", f"[SUBMIT] TIMEOUT seq={seq} dest={dest_addr}: {e}")
        return

    command_id, command_status, _, message_id = decode_submit_sm_resp(resp)
    if command_id == SUBMIT_SM_RESP and command_status == ESME_ROK:
        _stat('ok')
        log('info', f"[SUBMIT] OK {enc_label} {char_count} chars / "
            f"{len(message_bytes)} bytes: "
            f"message_id={message_id!r} dest={dest_addr}")
        if dr:
            register_submitted_message(message_id, dest_addr, message_text,
                                       data_coding=data_coding)
    elif command_id != SUBMIT_SM_RESP:
        _stat('unexpected')
        log("warning", f"[SUBMIT] Unexpected response PDU: "            f"cmd=0x{command_id:08X} (expected 0x{SUBMIT_SM_RESP:08X}) "            f"seq={seq} dest={dest_addr}")
    else:
        _stat('failed')
        status_msg = STATUS_CODES.get(command_status, "Unknown status")
        log("warning", f"[SUBMIT] FAILED seq={seq} dest={dest_addr}: "            f"0x{command_status:08X} ({status_msg})")


def _segment_and_submit(sock, dest_addr, message_text, data_coding,
                        request_dr=True):
    """
    Core multipart engine used by submit_long_sm.
    Segments text correctly for each data_coding, adds UDH, submits each part.

    Segmentation rules (SMPP 3.4 / GSM 03.40):
      0x03 Latin1: split by BYTE count (133 bytes/part), raw ISO-8859-1
      0x08 UCS2  : split by CHAR count (66 chars/part),  then UTF-16 BE each segment
    """
    _, enc_label, _ = _encode_message(message_text, data_coding)

    # ── Build char/byte segments ──────────────────────────────────────────
    if data_coding == DATA_CODING_UCS2:
        # Segment by char count (66 chars x 2 bytes + 7 UDH = 139 bytes <= 140)
        chars_per_seg = UCS2_UDH_MAX_BYTES // 2          # 66 chars
        char_segs     = [message_text[i:i+chars_per_seg]
                         for i in range(0, len(message_text), chars_per_seg)]
        byte_segs     = [s.encode('utf-16-be') for s in char_segs]

    else:  # Latin1 0x03
        # Segment by byte count (133 bytes + 7 UDH = 140 bytes)
        raw           = message_text.encode('iso-8859-1', errors='replace')
        byte_segs     = [raw[i:i+LATIN1_UDH_MAX_BYTES]
                         for i in range(0, len(raw), LATIN1_UDH_MAX_BYTES)]
        char_segs     = [s.decode('iso-8859-1') for s in byte_segs]

    total   = len(byte_segs)
    ref_num = next_sequence() & 0xFF
    log("info", f"[SUBMIT-LONG] {enc_label} | {len(message_text)} chars -> "          f"{total} part(s) | ref=0x{ref_num:02X}")

    for i, (seg_text, seg_bytes) in enumerate(zip(char_segs, byte_segs), start=1):
        # Multipart (ESM=0x40): sm_length = total byte count regardless of encoding.
        # sm_length = total byte count (UDH path uses len(payload))
        seq, pdu = _build_submit_sm_pdu(
            CFG['source_addr'], dest_addr, seg_bytes,
            data_coding=data_coding,
            ref_num=ref_num, total_parts=total, part_num=i,
            request_dr=request_dr)
        send_pdu(sock, pdu)
        _stat('sent')
        try:
            resp = _wait_submit_resp(seq)
        except TimeoutError as e:
            _stat('timeout')
            log("warning", f"[SUBMIT-LONG] Part {i}/{total} TIMEOUT "                f"seq={seq} dest={dest_addr}: {e}")
            continue
        command_id, command_status, _, message_id = decode_submit_sm_resp(resp)
        if command_id == SUBMIT_SM_RESP and command_status == ESME_ROK:
            _stat('ok')
            label = f"{message_text[:15]}...[{enc_label} {i}/{total}]"
            log("info", f"[SUBMIT-LONG] Part {i}/{total} OK: "                f"{len(seg_text)} chars / {len(seg_bytes)} bytes | "                f"message_id={message_id!r}")
            if request_dr:
                register_submitted_message(message_id, dest_addr, label,
                                           data_coding=data_coding)
        elif command_id != SUBMIT_SM_RESP:
            _stat('unexpected')
            log("warning", f"[SUBMIT-LONG] Part {i}/{total} unexpected response PDU: "                f"cmd=0x{command_id:08X} (expected 0x{SUBMIT_SM_RESP:08X}) "                f"seq={seq} dest={dest_addr}")
        else:
            _stat('failed')
            status_msg = STATUS_CODES.get(command_status, "Unknown status")
            log("warning", f"[SUBMIT-LONG] Part {i}/{total} FAILED "                f"seq={seq} dest={dest_addr}: "                f"0x{command_status:08X} ({status_msg})")


def submit_long_sm(sock, dest_addr, message_text, data_coding=DATA_CODING_LATIN1,
                   request_dr=None):
    """
    Submit a long message, splitting into multipart UDH segments as needed.
    Falls through to submit_sm if message fits in a single SMS.
    data_coding: DATA_CODING_LATIN1 (0x03) | DATA_CODING_UCS2 (0x08)
    request_dr : True/False or None to use CFG['request_dr']
    """
    dr = CFG['request_dr'] if request_dr is None else request_dr
    _, enc_label, char_count = _encode_message(message_text, data_coding)

    # Check if it fits in a single SMS
    if data_coding == DATA_CODING_UCS2:
        fits = char_count <= (UCS2_MAX_BYTES // 2)
    else:
        fits = len(message_text.encode('iso-8859-1', errors='replace')) <= LATIN1_MAX_BYTES

    if fits:
        log("info", f"[INFO] {enc_label} message fits in one SMS ({char_count} chars); "            f"submitting normally.")
        submit_sm(sock, dest_addr, message_text, data_coding=data_coding,
                  request_dr=dr)
        return

    _segment_and_submit(sock, dest_addr, message_text, data_coding,
                        request_dr=dr)


def send_unbind(sock):
    """
    Send UNBIND PDU to gracefully notify the SMSC we are disconnecting.
    We do NOT attempt to read the UNBIND_RESP here because pdu_receiver_worker
    may still be running and would consume it first (race condition on the socket).
    The SMSC will receive our UNBIND and clean up its side regardless.
    """
    try:
        seq = next_sequence()
        send_pdu(sock, struct.pack('>IIII', 16, UNBIND, 0, seq))
        log('info', f"[UNBIND] Sent unbind (seq={seq}) - closing session")
    except Exception as e:
        log('debug', f"[UNBIND] Error sending unbind: {e}")


def send_enquire_link(sock):
    seq = next_sequence()
    send_pdu(sock, struct.pack('>IIII', 16, ENQUIRE_LINK, 0, seq))
    return seq


def send_enquire_link_resp(sock, seq):
    send_pdu(sock, struct.pack('>IIII', 16, ENQUIRE_LINK_RESP, ESME_ROK, seq))


def send_deliver_sm_resp(sock, seq):
    # body = null byte (empty message_id field)
    send_pdu(sock, struct.pack('>IIIIB', 17, DELIVER_SM_RESP, ESME_ROK, seq, 0))

# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------

def enquire_link_worker(sock, stop_event):
    """Send enquire_link every CFG[el_interval] seconds."""
    log("info", f"[EL] Keep-alive thread started (interval={CFG['el_interval']}s)")
    while not stop_event.wait(CFG['el_interval']):
        try:
            seq = send_enquire_link(sock)
            log("debug", f"[EL] Sent enquire_link seq={seq}")
        except Exception as e:
            log("error", f"[EL] Error: {e}")
            stop_event.set()
            break
    log("info", "[EL] Keep-alive thread stopped")


def dr_monitor_worker(stop_event):
    """Periodically print messages still awaiting a DR."""
    log("info", f"[DR-MON] DR monitor started (check every {CFG['dr_check_interval']}s)")
    while not stop_event.wait(CFG['dr_check_interval']):
        check_pending_dr()
    log("info", "[DR-MON] DR monitor stopped")


def pdu_receiver_worker(sock, stop_event):
    """
    Reads ALL incoming PDUs and dispatches them:
      - SUBMIT_SM_RESP  -> routed to _submit_resp_queue (consumed by submit_sm)
      - DELIVER_SM      -> DR processing or MO display, then deliver_sm_resp
      - ENQUIRE_LINK    -> immediate enquire_link_resp
      - ENQUIRE_LINK_RESP -> logged
    Uses select() with 1s timeout so it checks stop_event regularly.
    """
    while not stop_event.is_set():
        try:
            readable, _, _ = select.select([sock], [], [], 1.0)
        except Exception:
            break
        if not readable:
            continue

        try:
            pdu = read_pdu(sock)
        except Exception as e:
            if not stop_event.is_set():
                log("error", f"[RX] Connection lost: {e}")
                stop_event.set()
            break

        _, command_id, command_status, seq = parse_header(pdu)

        # --- submit_sm_resp: route to queue, never handle here directly ---
        if command_id == SUBMIT_SM_RESP:
            _submit_resp_queue.put(pdu)

        # --- deliver_sm: DR or MO ---
        elif command_id == DELIVER_SM:
            try:
                (_, _, seq, esm_class,
                 src, dst, data_coding, short_msg) = decode_deliver_sm(pdu)
            except Exception as e:
                log("error", f"[RX] Failed to decode deliver_sm: {e}")
                try:
                    send_deliver_sm_resp(sock, seq)
                except Exception:
                    pass
                continue

            if esm_class & ESM_CLASS_DELIVERY_RECEIPT:
                # Pass raw bytes; process_delivery_receipt decodes text:
                # field using the stored original data_coding
                process_delivery_receipt(seq, short_msg, data_coding)
            else:
                # MO: decode using the deliver_sm's own data_coding
                mo_text = _decode_sm_bytes(short_msg, data_coding)
                log("info", f"[MO] From={src} To={dst} "
                      f"dc=0x{data_coding:02X} msg={mo_text!r}")

            try:
                send_deliver_sm_resp(sock, seq)
                log("debug", f"[RX] deliver_sm_resp sent (seq={seq})")
            except Exception as e:
                log("error", f"[RX] Failed to send deliver_sm_resp: {e}")

        # --- enquire_link from SMSC: reply immediately ---
        elif command_id == ENQUIRE_LINK:
            try:
                send_enquire_link_resp(sock, seq)
                log("debug", f"[EL] enquire_link from SMSC (seq={seq}) -> replied")
            except Exception as e:
                log("error", f"[EL] Failed to send enquire_link_resp: {e}")

        # --- enquire_link_resp: just log ---
        elif command_id == ENQUIRE_LINK_RESP:
            log("debug", f"[EL] enquire_link_resp received (seq={seq})")

        else:
            log("warning", f"[RX] Unhandled PDU: "
                  f"cmd=0x{command_id:08X} seq={seq} "
                  f"status=0x{command_status:08X}")

# ---------------------------------------------------------------------------
# Menu helpers
# ---------------------------------------------------------------------------

def prompt(label, default=None):
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"  {label}{suffix}: ").strip()
    return val if val else default


def _pick_data_coding(mode):
    """
    Present 2 data_coding choices and return (data_coding_int, default_text).
    mode: 'short' or 'long'

    0x03 Latin1: 8-bit ISO-8859-1, English text,  max 140 bytes/SMS (133/part)
    0x08 UCS2  : 8-bit UTF-16 BE,  Unicode/CJK,   max 70 chars/SMS  ( 66/part)
    """
    print("  data_coding:")
    print("    1  0x03  Latin1 - ISO-8859-1  (English, max 140 bytes/SMS)")
    print("    2  0x08  UCS2   - UTF-16 BE   (Unicode/CJK, max 70 chars/SMS)")
    choice = input("  Choice [1]: ").strip()
    if choice == '2':
        dc           = DATA_CODING_UCS2
        default_text = (CFG['default_ucs2_short_text'] if mode == 'short'
                        else CFG['default_ucs2_long_text'])
    else:
        dc           = DATA_CODING_LATIN1
        default_text = (CFG['default_short_text'] if mode == 'short'
                        else CFG['default_long_text'])
    return dc, default_text


# ---------------------------------------------------------------------------
# Load test state  (shared between sender thread and resp-collector thread)
# ---------------------------------------------------------------------------
_lt_lock       = threading.Lock()
_lt_seq_map    = {}    # seq -> {'dest', 'text', 'dc', 'tagged_text'}
_lt_done_event = threading.Event()


def _lt_resp_collector(expected_count, deadline, result_box):
    """
    Background thread: drain _submit_resp_queue in real-time during the
    load test send loop.  Registers each message_id immediately so that
    DRs arriving while we are still sending will find the entry and NOT
    trigger the UNKNOWN warning.

    result_box[0] = (ok, fail, timed_out)  written when done.
    """
    ok   = 0
    fail = 0
    seen = 0

    while seen < expected_count and time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            pdu = _submit_resp_queue.get(timeout=min(remaining, 0.2))
        except queue.Empty:
            continue

        _, cmd_id, cmd_status, resp_seq = parse_header(pdu)

        # Look up metadata registered by the sender
        with _lt_lock:
            meta = _lt_seq_map.get(resp_seq)

        if meta is None:
            # Not one of ours - discard it (it belongs to a non-load-test
            # operation; load tests should not be mixed with manual submits).
            # Putting it back risks an infinite busy-loop if it keeps coming.
            log('debug', f"[LT] Discarding non-LT PDU in collector seq={resp_seq}")
            continue

        seen += 1
        message_id = pdu[16:].split(b'\x00', 1)[0].decode('ascii', errors='replace')

        if cmd_id == SUBMIT_SM_RESP and cmd_status == ESME_ROK:
            ok += 1
            # Register NOW so any DR arriving immediately finds the entry
            # Only register if DR was requested - no point tracking if SMSC won't send one
            if meta.get('request_dr', True):
                register_submitted_message(message_id,
                                           meta['dest'],
                                           meta['tagged_text'],
                                           data_coding=meta['dc'])
            log('debug', f"[LT] resp OK seq={resp_seq} message_id={message_id!r}")
        else:
            fail += 1
            status_msg = STATUS_CODES.get(cmd_status, "Unknown")
            dest_info  = meta.get('dest', '?')
            log('warning', f"[LT] FAILED seq={resp_seq} dest={dest_info}: "                f"0x{cmd_status:08X} ({status_msg})")

    timed_out      = expected_count - seen
    result_box[0]  = (ok, fail, timed_out)
    _lt_done_event.set()


def menu_submit_sm(sock):
    print("\n-- Submit Short Message --")
    dest = prompt("Destination address", CFG['default_dest'])
    if not dest:
        print("[ERROR] Destination address is required.")
        return
    dc, default_text = _pick_data_coding('short')
    text = input(f"  Message text [{default_text[:60]}]: ").strip()
    if not text:
        text = default_text

    # ── Load test options ────────────────────────────────────────────────
    raw_count = input("  Number of messages [1]: ").strip()
    try:
        count = int(raw_count) if raw_count else 1
        if count < 1:
            count = 1
    except ValueError:
        print("[ERROR] Invalid count, using 1.")
        count = 1

    if count == 1:
        submit_sm(sock, dest, text, data_coding=dc)
        return

    raw_tps = input("  Target TPS (messages/sec) [10]: ").strip()
    try:
        tps = float(raw_tps) if raw_tps else 10.0
        if tps <= 0:
            tps = 10.0
    except ValueError:
        print("[ERROR] Invalid TPS, using 10.")
        tps = 10.0

    interval   = 1.0 / tps          # seconds between each send
    resp_wait  = CFG['resp_timeout'] # seconds to wait for all resps after send

    print(f"\n[LT] Starting load test: {count} msgs @ {tps} TPS "
          f"(interval={interval*1000:.1f}ms)")
    log('info', f"[LT] Load test start: count={count} tps={tps} "
        f"dest={dest} dc=0x{dc:02X}")

    lt_dr = CFG['request_dr']   # snapshot once for whole load test

    # ── Prepare shared state for the resp-collector thread ──────────────
    with _lt_lock:
        _lt_seq_map.clear()
    _lt_done_event.clear()

    # Deadline = generous: all sends + resp_timeout + 50ms per msg
    lt_deadline  = time.time() + (count / tps) + resp_wait + 30  # 30s flat buffer after last send
    result_box   = [None]   # collector writes (ok, fail, timed_out) here

    # Start resp-collector thread BEFORE the first send so no resp is missed
    collector = threading.Thread(
        target=_lt_resp_collector,
        args=(count, lt_deadline, result_box),
        daemon=True, name="lt-resp-collector")
    collector.start()

    sent             = 0
    send_errors      = 0
    t_start          = time.time()
    _lt_last_progress = t_start - 5.0  # force immediate first print

    for i in range(1, count + 1):
        # Append [i/count] so each SMS is uniquely identifiable
        tagged_text = f"{text} [{i}/{count}]"
        msg_bytes, _, _ = _encode_message(tagged_text, dc)
        seq, pdu = _build_submit_sm_pdu(CFG['source_addr'], dest,
                                         msg_bytes, data_coding=dc,
                                         request_dr=lt_dr)
        try:
            # Register seq metadata BEFORE sending so the collector thread
            # can match the response even if it arrives instantly
            with _lt_lock:
                _lt_seq_map[seq] = {
                    'dest':        dest,
                    'text':        text,
                    'tagged_text': tagged_text,
                    'dc':          dc,
                    'request_dr':  lt_dr,
                }
            send_pdu(sock, pdu)
            sent += 1
        except Exception as e:
            log('error', f"[LT] Send error at msg {i}: {e}")
            with _lt_lock:
                _lt_seq_map.pop(seq, None)
            send_errors += 1

        # Progress: every 5 seconds or at count boundaries
        # (avoids 10,000 prints for a 100K run while still being responsive)
        now_t = time.time()
        if now_t - _lt_last_progress >= 5.0 or i == count:
            _lt_last_progress = now_t
            elapsed    = now_t - t_start
            actual_tps = sent / elapsed if elapsed > 0 else 0
            print(f"  [LT] Sent {sent:,}/{count:,} | "
                  f"elapsed={elapsed:.1f}s | actual TPS={actual_tps:.1f}",
                  end='\r', flush=True)

        # Rate limiting: absolute-time anchored to avoid drift
        if i < count:
            next_send = t_start + i * interval
            sleep_for = next_send - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)

    t_send_done  = time.time()
    elapsed_send = t_send_done - t_start
    print()   # end the \r progress line
    log('info', f"[LT] All {sent} PDUs sent in {elapsed_send:.3f}s "
        f"(avg {sent/elapsed_send:.1f} TPS) | send_errors={send_errors}")

    # ── Wait for collector to finish ──────────────────────────────────────
    remaining_wait = lt_deadline - time.time()
    if remaining_wait > 0:
        print(f"[LT] Waiting up to {remaining_wait:.0f}s for {sent:,} resp(s)...")
        _lt_done_event.wait(timeout=remaining_wait)
    collector.join(timeout=2.0)

    ok, fail, timed_out = result_box[0] if result_box[0] else (0, 0, sent)
    _stat('sent',    sent)
    _stat('ok',      ok)
    _stat('failed',  fail)
    _stat('timeout', timed_out)
    t_done        = time.time()
    total_elapsed = t_done - t_start

    # ── Summary ──────────────────────────────────────────────────────────
    print()
    print("=" * 52)
    print("  Load Test Summary")
    print("=" * 52)
    print(f"  Messages submitted  : {sent:,}")
    print(f"  Send errors         : {send_errors}")
    print(f"  Resp OK             : {ok:,}")
    print(f"  Resp FAILED         : {fail:,}")
    print(f"  Resp timed out      : {timed_out:,}")
    print(f"  Send duration       : {elapsed_send:.3f}s")
    print(f"  Total duration      : {total_elapsed:.3f}s")
    print(f"  Avg send TPS        : {sent/elapsed_send:.1f}")
    if ok > 0:
        print(f"  Avg resp TPS        : {ok/(total_elapsed):.1f}")
    print("=" * 52)
    log('info', f"[LT] Summary: sent={sent} ok={ok} fail={fail} "
        f"timeout={timed_out} send_dur={elapsed_send:.3f}s")


def menu_submit_long_sm(sock):
    print("\n-- Submit Long Message (multipart UDH) --")
    dest = prompt("Destination address", CFG['default_dest'])
    if not dest:
        print("[ERROR] Destination address is required.")
        return
    dc, default_text = _pick_data_coding('long')
    print(f"  Default text ({len(default_text)} chars): {default_text[:70]}...")
    text = input("  Message text [Enter for default]: ").strip()
    if not text:
        text = default_text
    submit_long_sm(sock, dest, text, data_coding=dc)


def menu_send_enquire_link(sock):
    print("\n-- Manual Enquire Link --")
    seq = send_enquire_link(sock)
    print(f"[EL] enquire_link sent (seq={seq})")


def _print_dr_table(rows, now, page, total_pages, page_size):
    """Print one page of DR rows."""
    print(f"  {'message_id':<36} {'dest':<15} {'age(s)':<8} {'DR?':<5} stat")
    print(f"  {'-'*36} {'-'*15} {'-'*8} {'-'*5} ----")
    for mid, e in rows:
        age     = now - e['submitted_at']
        dr_flag = "YES" if e['dr_received'] else "NO"
        stat    = e['dr_stat'] or "-"
        print(f"  {mid:<36} {e['dest']:<15} {age:<8.0f} {dr_flag:<5} {stat}")
    print(f"  -- Page {page}/{total_pages} --")


def menu_show_pending_dr():
    print("\n-- Submit & DR Status --")

    # ── Section 1: Submit outcome counters (always shown) ────────────────
    with _submit_stats_lock:
        ss = dict(_submit_stats)   # snapshot

    resp_total = ss['ok'] + ss['failed'] + ss['timeout'] + ss['unexpected']
    print("  Submit Statistics")
    print(f"    PDUs sent          : {ss['sent']:,}")
    print(f"    Resp OK  (ESME_ROK): {ss['ok']:,}")
    print(f"    Resp FAILED        : {ss['failed']:,}")
    print(f"    Resp timeout       : {ss['timeout']:,}")
    print(f"    Resp unexpected    : {ss['unexpected']:,}")
    if ss['sent'] > 0:
        pct = ss['ok'] / ss['sent'] * 100
        print(f"    Success rate       : {pct:.1f}%")

    if ss['sent'] == 0:
        print("  (no messages submitted yet)")
        return

    print()

    # ── Section 2: DR summary (only if any messages tracked) ─────────────
    with _pending_dr_lock:
        snapshot = list(_pending_dr.items())

    if not snapshot:
        print("  DR Tracking: disabled or no DR-enabled messages submitted")
        return

    from collections import Counter
    now      = time.time()
    total    = len(snapshot)
    received = sum(1 for _, e in snapshot if e['dr_received'])
    pending  = total - received

    print("  DR Tracking")
    print(f"    Tracked messages   : {total:,}")
    print(f"    DR received        : {received:,}  ({received/total*100:.1f}%)")
    print(f"    Awaiting DR        : {pending:,}")

    stat_counts = Counter(
        e['dr_stat'] if e['dr_received'] else 'PENDING'
        for _, e in snapshot
    )
    print("    Breakdown          :", "  ".join(
        f"{s}={c:,}" for s, c in sorted(stat_counts.items())))

    if total == 0:
        return

    # ── Sub-menu ─────────────────────────────────────────────────────────
    PAGE_SIZE = 50
    while True:
        print()
        print("  View:")
        print("    1  Show pending (no DR yet)")
        print("    2  Show failed  (UNDELIV / REJECTD / EXPIRED)")
        print("    3  Show all     (paginated)")
        print("    0  Back")
        sub = input("  Choice [0]: ").strip()

        if sub == '0' or sub == '':
            break

        elif sub == '1':
            rows = [(m, e) for m, e in snapshot if not e['dr_received']]
            label = "Pending (no DR)"

        elif sub == '2':
            failed_stats = {'UNDELIV', 'REJECTD', 'EXPIRED', 'DELETED'}
            rows = [(m, e) for m, e in snapshot
                    if e['dr_received'] and e['dr_stat'] in failed_stats]
            label = "Failed DRs"

        elif sub == '3':
            rows = snapshot
            label = "All"

        else:
            print("  [WARN] Unknown choice.")
            continue

        if not rows:
            print(f"  (no entries for: {label})")
            continue

        # Paginate
        total_pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = 1

        if len(rows) > PAGE_SIZE:
            print(f"  {label}: {len(rows):,} entries | {total_pages} pages of {PAGE_SIZE}")

        while True:
            now = time.time()
            start = (page - 1) * PAGE_SIZE
            page_rows = rows[start:start + PAGE_SIZE]
            print(f"\n  -- {label} | Page {page}/{total_pages} --")
            _print_dr_table(page_rows, now, page, total_pages, PAGE_SIZE)

            if total_pages == 1:
                break

            nav = input("  [n]ext  [p]rev  [q]uit  [page#]: ").strip().lower()
            if nav == 'q' or nav == '':
                break
            elif nav == 'n':
                page = min(page + 1, total_pages)
            elif nav == 'p':
                page = max(page - 1, 1)
            else:
                try:
                    pg = int(nav)
                    if 1 <= pg <= total_pages:
                        page = pg
                    else:
                        print(f"  Page must be 1-{total_pages}")
                except ValueError:
                    print("  Invalid input.")


def _print_config():
    print("\n-- Current Configuration --")
    print(f"  [1] Server            : {CFG['server']}:{CFG['port']}")
    print(f"  [2] System ID         : {CFG['system_id']}")
    print(f"  [3] Password          : {'*' * len(CFG['password'])}")
    print(f"  [4] System Type       : {CFG['system_type']!r}")
    print(f"  [5] Source Address    : {CFG['source_addr']}")
    print(f"  [6] EL Interval       : {CFG['el_interval']}s")
    print(f"  [7] DR Check Interval : {CFG['dr_check_interval']}s")
    print(f"  [8] Resp Timeout      : {CFG['resp_timeout']}s")
    print(f"  [9] Default Dest        : {CFG['default_dest']}")
    print(f"  [A] Default Short Text  : {CFG['default_short_text']}")
    print(f"  [B] Default Long Text   : {CFG['default_long_text'][:60]}...")
    dr_label = 'YES (0x01 - SMSC sends DR)' if CFG['request_dr'] else 'NO  (0x00 - no DR)'
    print(f"  [C] Request DR          : {dr_label}")
    print(f"  [0] Back to main menu")


def menu_show_config():
    global CFG
    while True:
        _print_config()
        key = input("  Edit [1-9/A-C/R=reload] or 0 to go back: ").strip().upper()
        if key == '0' or key == '':
            break
        elif key == '1':
            val = prompt("Server host", CFG['server'])
            raw_port = prompt("Port", str(CFG['port']))
            try:
                port_int = int(raw_port)
                if not 1 <= port_int <= 65535:
                    raise ValueError("out of range")
                CFG['server'] = val
                CFG['port']   = port_int
                if _save_ini(): print(f"[CFG] Server updated -> saved to {INI_FILE} (reconnect required).")
            except ValueError:
                print("[ERROR] Port must be an integer between 1 and 65535.")
        elif key == '2':
            val = prompt("System ID", CFG['system_id'])
            if val and len(val) > 16:
                print("[ERROR] System ID max length is 16 chars (SMPP spec).")
            elif val:
                CFG['system_id'] = val
                if _save_ini(): print(f"[CFG] System ID updated -> saved to {INI_FILE} (reconnect required).")
        elif key == '3':
            import getpass
            val = getpass.getpass("  New password: ")
            if len(val) > 9:
                print("[ERROR] Password max length is 9 chars (SMPP spec).")
            elif val:
                CFG['password'] = val
                if _save_ini(): print(f"[CFG] Password updated -> saved to {INI_FILE} (reconnect required).")
        elif key == '4':
            val = prompt("System Type", CFG['system_type'])
            CFG['system_type'] = val
            if _save_ini(): print(f"[CFG] System Type updated -> saved to {INI_FILE}.")
        elif key == '5':
            val = prompt("Source Address", CFG['source_addr'])
            CFG['source_addr'] = val
            if _save_ini(): print(f"[CFG] Source Address updated -> saved to {INI_FILE}.")
        elif key == '6':
            raw = prompt("EL Interval (seconds)", str(CFG['el_interval']))
            try:
                CFG['el_interval'] = int(raw)
                if _save_ini(): print(f"[CFG] EL Interval updated -> saved to {INI_FILE}.")
            except ValueError:
                print("[ERROR] Must be an integer.")
        elif key == '7':
            raw = prompt("DR Check Interval (seconds)", str(CFG['dr_check_interval']))
            try:
                CFG['dr_check_interval'] = int(raw)
                if _save_ini(): print(f"[CFG] DR Check Interval updated -> saved to {INI_FILE}.")
            except ValueError:
                print("[ERROR] Must be an integer.")
        elif key == '8':
            raw = prompt("Resp Timeout (seconds)", str(CFG['resp_timeout']))
            try:
                CFG['resp_timeout'] = int(raw)
                if _save_ini(): print(f"[CFG] Resp Timeout updated -> saved to {INI_FILE}.")
            except ValueError:
                print("[ERROR] Must be an integer.")
        elif key == '9':
            val = prompt("Default Destination", CFG['default_dest'])
            CFG['default_dest'] = val
            if _save_ini(): print(f"[CFG] Default Destination updated -> saved to {INI_FILE}.")
        elif key == 'A':
            val = prompt("Default Short Text", CFG['default_short_text'])
            CFG['default_short_text'] = val
            if _save_ini(): print(f"[CFG] Default Short Text updated -> saved to {INI_FILE}.")
        elif key == 'B':
            print(f"  Current: {CFG['default_long_text']}")
            val = input("  New long text (Enter to keep): ").strip()
            if val:
                CFG['default_long_text'] = val
                if _save_ini(): print(f"[CFG] Default Long Text updated -> saved to {INI_FILE}.")
        elif key == 'C':
            cur = 'YES' if CFG['request_dr'] else 'NO'
            val = input(f"  Request DR [{cur}] (y/n): ").strip().lower()
            if val in ('y', 'yes', '1'):
                CFG['request_dr'] = True
                if _save_ini(): print(f"[CFG] Request DR enabled -> saved to {INI_FILE}.")
            elif val in ('n', 'no', '0'):
                CFG['request_dr'] = False
                if _save_ini(): print(f"[CFG] Request DR disabled -> saved to {INI_FILE}.")
            elif val == '':
                print("[CFG] Unchanged.")
            else:
                print("[ERROR] Enter y or n.")
        elif key == 'R':
            CFG = _load_ini()
            ini_path = os.path.abspath(INI_FILE)
            if os.path.exists(INI_FILE):
                print(f"[CFG] Reloaded from {ini_path}")
            else:
                print(f"[CFG] {INI_FILE} not found, using defaults")
        else:
            print("[WARN] Unknown option.")


def print_menu():
    print("\n" + "="*50)
    print("  Generic SMPP Client - Main Menu")
    print("="*50)
    print("  1  Submit short message")
    print("  2  Submit long message (multipart)")
    print("  3  Send enquire_link manually")
    print("  4  Show pending DR status")
    print("  5  Show configuration")
    print("  0  Quit")
    print("="*50)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("info", "Generic SMPP Client")
    ini_status = (f"Loaded: {os.path.abspath(INI_FILE)}"
                  if os.path.exists(INI_FILE)
                  else f"Not found: {INI_FILE} -- using built-in defaults")
    log("info", f"Config: {ini_status}")
    log("info", f"Debug log: {os.path.abspath(LOG_FILE)}")
    log("info", f"Connecting to {CFG['server']}:{CFG['port']} ...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30.0)          # connect timeout
        sock.connect((CFG['server'], CFG['port']))
        sock.settimeout(None)          # back to blocking for normal operation
        # TCP keepalive so OS detects silent drops
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        log("info", "Connected.")
    except socket.error as e:
        log("error", f"[ERROR] Cannot connect: {e}")
        return

    if not bind_transceiver(sock):
        sock.close()
        return

    stop_event = threading.Event()

    # Thread 1: keep-alive enquire_link
    t_el = threading.Thread(target=enquire_link_worker,
                             args=(sock, stop_event),
                             daemon=True, name="enquire-link")
    t_el.start()

    # Thread 2: all incoming PDUs
    t_rx = threading.Thread(target=pdu_receiver_worker,
                             args=(sock, stop_event),
                             daemon=True, name="pdu-receiver")
    t_rx.start()

    # Thread 3: periodic DR audit
    t_dr = threading.Thread(target=dr_monitor_worker,
                             args=(stop_event,),
                             daemon=True, name="dr-monitor")
    t_dr.start()

    try:
        while not stop_event.is_set():
            print_menu()
            try:
                choice = input("  Choice: ").strip()
            except (EOFError, KeyboardInterrupt):
                log("info", "Interrupt received.")
                break

            if stop_event.is_set():
                break

            if choice == '1':
                menu_submit_sm(sock)
            elif choice == '2':
                menu_submit_long_sm(sock)
            elif choice == '3':
                menu_send_enquire_link(sock)
            elif choice == '4':
                menu_show_pending_dr()
            elif choice == '5':
                menu_show_config()
            elif choice == '0':
                log("info", "Goodbye.")
                break
            else:
                print("[WARN] Unknown choice - please enter 0-5.")

    finally:
        stop_event.set()
        try:
            send_unbind(sock)
        except Exception:
            pass
        sock.close()
        log("info", "SMPP client stopped.")


if __name__ == "__main__":
    main()
