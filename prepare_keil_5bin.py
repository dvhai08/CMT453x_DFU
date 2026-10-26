"""Prepare a download-only Keil project and verify a merged Intel HEX."""
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(r'D:\hoperf\CMT453x_SDK_V1.9.0.0_GA')
DEMO = ROOT / 'utilities/dfu/Image/SingleBankProgrammingDemo'
MDK = ROOT / 'projects/cmt453x_EVAL/ble_peripheral/ble_rdts_peripheral_rf/MDK-ARM'
NAME = 'SingleBank_5BIN'
REGIONS = [('MasterBoot.bin', 0x01000000, 0x2000),
           ('bootsetting.bin', 0x01002000, 0x2000),
           ('APP1.bin', 0x01004000, 0x1C000),
           ('APP2.bin', 0x01020000, 0x1C000),
           ('ImageUpdate.bin', 0x0103C000, 0x4000)]


def record(kind, addr, data=b''):
    raw = bytes([len(data), addr >> 8, addr & 255, kind]) + data
    return ':' + (raw + bytes([-sum(raw) & 255])).hex().upper()


def main():
    for name, _, _ in REGIONS:
        if name != 'bootsetting.bin' and not (DEMO / 'Image' / name).is_file():
            raise FileNotFoundError(name)
    subprocess.run([str(ROOT / 'utilities/dfu/HPUtil/HPUtil.exe'),
                    'bootsetting', 'generate', 'Image/bootsetting.bin',
                    '--public_key_file', '../../keys/public_key.bin',
                    '--bank1_start_address', '0x01004000',
                    '--bank1_version', '0x00000001',
                    '--bank1_bin', 'Image/APP1.bin', '--bank1_activation', 'yes'],
                   cwd=DEMO, check=True)
    lines, expected, upper = [], {}, None
    for name, base, size in REGIONS:
        blob = (DEMO / 'Image' / name).read_bytes()
        if not 0 < len(blob) <= size:
            raise ValueError(f'{name}: invalid size {len(blob)}')
        for offset in range(0, len(blob), 16):
            address = base + offset
            if address >> 16 != upper:
                upper = address >> 16
                lines.append(record(4, 0, upper.to_bytes(2, 'big')))
            chunk = blob[offset:offset + 16]
            lines.append(record(0, address & 65535, chunk))
            for i, value in enumerate(chunk):
                if address + i in expected:
                    raise ValueError('Overlapping inputs')
                expected[address + i] = value
        print(f'{name}: {len(blob)} bytes @ 0x{base:08X}')
    lines.append(record(1, 0))
    output = DEMO / 'Image' / (NAME + '.hex')
    output.write_text('\n'.join(lines) + '\n', encoding='ascii')
    # Decode the saved file independently and compare every byte/address.
    actual, high, eof = {}, 0, False
    for line in output.read_text().splitlines():
        raw = bytes.fromhex(line[1:])
        assert line.startswith(':') and sum(raw) % 256 == 0
        assert len(raw) == raw[0] + 5 and not eof
        addr, kind, data = int.from_bytes(raw[1:3], 'big'), raw[3], raw[4:-1]
        if kind == 4:
            high = int.from_bytes(data, 'big') << 16
        elif kind == 0:
            for i, value in enumerate(data):
                assert high + addr + i not in actual
                actual[high + addr + i] = value
        elif kind == 1:
            eof = True
        else:
            raise ValueError(kind)
    assert eof and actual == expected
    source = MDK / 'ble_rdts_peripheral_rf.uvprojx'
    tree = ET.parse(source)
    targets = tree.getroot().find('Targets')
    first = targets[0]
    for target in list(targets)[1:]:
        targets.remove(target)
    first.find('TargetName').text = NAME
    common = first.find('TargetOption/TargetCommonOption')
    common.find('OutputDirectory').text = '..\\..\\..\\..\\..\\utilities\\dfu\\Image\\SingleBankProgrammingDemo\\Image\\'
    common.find('OutputName').text = NAME + '.hex'
    common.find('CreateHexFile').text = '0'
    for stage in ('BeforeCompile', 'BeforeMake', 'AfterMake'):
        for flag in ('RunUserProg1', 'RunUserProg2'):
            common.find(stage + '/' + flag).text = '0'
    groups = first.find('Groups')
    if groups is not None:
        first.remove(groups)
    ET.indent(tree, space='  ')
    project = MDK / (NAME + '.uvprojx')
    tree.write(project, encoding='utf-8', xml_declaration=True)
    options = ET.parse(MDK / 'ble_rdts_peripheral_rf.uvoptx')
    root = options.getroot()
    all_targets = root.findall('Target')
    all_targets[0].find('TargetName').text = NAME
    for target in all_targets[1:]:
        root.remove(target)
    ET.indent(options, space='  ')
    options.write(MDK / (NAME + '.uvoptx'), encoding='utf-8', xml_declaration=True)
    resolved = (MDK / common.find('OutputDirectory').text / common.find('OutputName').text).resolve()
    assert resolved == output.resolve(), (resolved, output)
    ET.parse(project)
    print(f'VERIFIED: {len(actual)} bytes, all checksums and input bytes match.')
    print(f'HEX: {output}')
    print(f'PROJECT: {project}')


if __name__ == '__main__':
    main()
