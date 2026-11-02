# CMF Buds Pro 2 (B172) protocol

These values were confirmed live on firmware **1.0.1.74** from Windows. The connection is RFCOMM **channel 15**.
Sources: the something-x, EarA and ear-web projects, all derived from the Nothing X APK, plus live probing with `tools/probe.py`.

## Frame
```
55 | ctrl u16 LE | cmd u16 LE | len u16 LE | seq u8 | payload | crc16 u16 LE
```
- The host always sends `ctrl=0x0160` and appends a CRC16-ARC (init 0xFFFF, poly 0xA001) over everything before it.
- The device clears bit 15 of `cmd` in its replies (for example `0xC007` comes back as `0x4007`). The device's CRCs don't validate, so ignore them on receive.
- Session start: send `C001` (protocol version), then `F001` (activate). Any GET/SET sent before that is ignored.

## Commands
| Cmd | Dir | Payload | Notes |
|---|---|---|---|
| C006 | get | – | info lines `dev,field,value`; field 4 = serial, 2 = fw |
| C007 / E001 | get/evt | `n, (type,val)*n` | type 2 L, 3 R, 4 case; val bit7 = charging, low 7 bits = % |
| C00A / E002 | get/evt | `n, (type,val)*n` | bit2 = in ear, bit7 = connected. The event only refreshes the bud that changed, so re-query. |
| C00E | get | `n, (id,val)*n` | settings flags; id 1 = in-ear detection |
| F004 | set | `01 01 on` | in-ear detection |
| C018 | get | `n, (device,button,type,action)*n` | gestures |
| F003 | set | `01 device button type action` | one gesture slot |
| C01E / E003 | get/evt | `(type,val,0)*` | type 1 = mode |
| F00F | set | `01 mode 00` | ANC: 1 high, 2 mid, 3 low, 4 adaptive, 5 off, 7 transparency |
| C050 / F01D | get/set | `mode [00]` | listening mode: 0 Balanced, 1 Rock, 2 Electronic, 3 Pop, 4 Vocals, 5 Classical, 6 Custom |
| C044 / F041 | get/set | 53-byte biquad table | custom EQ; gains (float LE) at offsets 6/19/32 = mid/treble/bass, range ±6 |
| C041 / F040 | get/set | `1=on 2=off [00]` | low-lag mode |
| C04E / F051 | get/set | `on, level*2` | Ultra Bass, level 1–5 |
| F002 | set | `side on` | ring: side 1 both, 2 L, 3 R; on 0/1 |
| C042 | get | ASCII | firmware |

## Gesture slots
Devices: `2` left bud, `3` right bud, `4` case Smart Dial. Button `1` = normal; button `9` = the dial's during-call slot.
Types: `1` single, `2` double, `3` triple, `7` press & hold, `9` double press & hold, `10` rotate.

| Action | | Action | |
|---|---|---|---|
| 1 | No action | 17 | Low lag on/off |
| 2 | Play/Pause | 18 / 19 | Volume up / down |
| 3 | Answer call | 10, 20–22 | Noise control (cycle variants) |
| 8 / 9 | Skip back / forward | 23 | Volume control (dial rotate) |
| 11 | Voice assistant | 25 / 26 | Answer + mute mic / Hang up |

The allowed actions for each slot are listed in `OPTIONS` in `buds.py`.

Live dial dump: `04 01 01 02` (single → play/pause), `04 01 0a 17` (rotate → volume), `04 09 02 19`, `04 09 03 1a`.
