"""Inspect native instructions around build-relative addresses from a probe exit.

Run with: uv run --with pefile --with capstone python disassemble.py EXE RVA ...
"""
import argparse
import capstone
import pefile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    parser.add_argument("rvas", nargs="+", type=lambda s: int(s, 0))
    args = parser.parse_args()
    pe = pefile.PE(args.executable, fast_load=True)
    image = pe.get_memory_mapped_image()
    base = pe.OPTIONAL_HEADER.ImageBase
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    for rva in args.rvas:
        print(f"RVA {rva:#x}")
        start = max(0, rva - 40)
        for inst in decoder.disasm(image[start:rva + 32], base + start):
            note = ""
            for operand in inst.operands:
                if operand.type == capstone.x86.X86_OP_MEM and operand.mem.base == capstone.x86.X86_REG_RIP:
                    target = inst.address + inst.size + operand.mem.disp - base
                    raw = image[target:target + 100].split(b"\0")[0]
                    if len(raw) > 3 and all(32 <= c < 127 for c in raw):
                        note = " ; " + raw.decode("ascii")
            print(f"  {inst.address-base:08x} {inst.mnemonic} {inst.op_str}{note}")


if __name__ == "__main__":
    main()
