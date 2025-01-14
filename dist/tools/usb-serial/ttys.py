#!/usr/bin/env python3
"""
Command line utility to list and filter TTYs
"""
import argparse
import json
import os
import re
import sys
import time

import pyudev


def unescape(string):
    """
    Decodes unicode escaping in a string, e.g. "Hallo\\x20World" is decoded as
    "Hallo World"
    """
    res = bytes(string, "utf8").decode("unicode_escape")
    res = res.encode("latin1").decode("utf8", errors="replace")
    return res


def tty2dict(dev):
    """
    Parse the given TTY udev interface into a dict() containing the most
    relevant attributes
    """
    result = {}
    result["path"] = dev.get("DEVNAME")
    result["ctime"] = os.stat(result["path"]).st_ctime
    result["serial"] = dev.get("ID_SERIAL_SHORT")
    result["driver"] = dev.get("ID_USB_DRIVER")
    result["model"] = unescape(dev.get("ID_MODEL_ENC"))
    result["model_db"] = dev.get("ID_MODEL_FROM_DATABASE")
    result["vendor"] = unescape(dev.get("ID_VENDOR_ENC"))
    result["vendor_db"] = dev.get("ID_VENDOR_FROM_DATABASE")
    result["iface_num"] = str(int(dev.get("ID_USB_INTERFACE_NUM")))

    return result


def filters_match(filters, tty):
    """
    Check if the given TTY interface matches all given filters
    """

    for key, regex in filters:
        if tty[key] is None:
            return False

        if not regex.match(tty[key]):
            return False

    return True


def parse_args(args):
    """
    Parse the given command line style arguments with argparse
    """
    desc = "List and filter TTY interfaces that might belong to boards"
    formats_combinable = {
        "path",
        "serial",
        "vendor",
        "vendor_db",
        "model",
        "model_db",
        "driver",
        "ctime",
        "iface_num",
    }
    formats_uncombinable = {
        "table",
        "json",
    }
    supported_formats = formats_combinable.union(formats_uncombinable)
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument("--most-recent", action="store_true",
                        help="Print only the most recently connected matching "
                             + "TTY")
    parser.add_argument("--format", default=["table"], type=str, nargs='+',
                        help=f"How to format the TTYs. Supported formats: "
                             f"{sorted(supported_formats)}")
    parser.add_argument("--format-sep", default=" ", type=str,
                        help="Separator between formats (default: space)")
    parser.add_argument("--serial", default=None, type=str,
                        help="Print only devices matching this serial")
    parser.add_argument("--driver", default=None, type=str,
                        help="Print only devices using a driver matching this "
                             "regex")
    parser.add_argument("--model", default=None, type=str,
                        help="Print only devices with a model matching this "
                             "regex (as reported from device)")
    parser.add_argument("--model-db", default=None, type=str,
                        help="Print only devices with a model matching this "
                             "regex (DB entry)")
    parser.add_argument("--vendor", default=None, type=str,
                        help="Print only devices with a vendor matching this "
                             "regex (as reported from device)")
    parser.add_argument("--vendor-db", default=None, type=str,
                        help="Print only devices with a vendor matching this "
                             "regex (DB entry)")
    parser.add_argument("--iface-num", default=None, type=str,
                        help="Print only devices with a USB interface number "
                             "matching this regex (DB entry)")
    parser.add_argument("--exclude-serial", type=str, nargs='*', default=None,
                        help="Ignore devices with these serial numbers. "
                             + "Environment variable EXCLUDE_TTY_SERIAL can "
                             + "be used alternatively.")

    args = parser.parse_args()

    if len(args.format) == 1:
        if args.format[0] not in supported_formats:
            sys.exit(f"Format \"{args.format[0]}\" not supported")
    else:
        for fmt in args.format:
            if fmt not in formats_combinable:
                if fmt in formats_uncombinable:
                    sys.exit(f"Format \"{fmt}\" cannot be combined with " +
                             "other formats")
                else:
                    sys.exit(f"Format \"{fmt}\" not supported")

    if args.exclude_serial is None:
        if "EXCLUDE_TTY_SERIAL" in os.environ:
            args.exclude_serial = os.environ["EXCLUDE_TTY_SERIAL"].split()
        else:
            args.exclude_serial = []

    return args


def print_table(data, headers):
    """
    Print the list of dictionaries given in data as table, where headers is
    a list of keys to that dict and also servers as table headers.
    """
    lengths = []
    for header in headers:
        lengths.append(len(header))

    for item in data:
        for i, header in enumerate(headers):
            if len(str(item[header])) > lengths[i]:
                lengths[i] = len(item[header])

    sys.stdout.write(f"{headers[0]:{lengths[0]}}")
    for i in range(1, len(headers)):
        sys.stdout.write(f" | {headers[i]:{lengths[i]}}")
    sys.stdout.write("\n" + lengths[0] * "-")
    for i in range(1, len(headers)):
        sys.stdout.write("-|-" + lengths[i] * "-")

    for item in data:
        sys.stdout.write(f"\n{str(item[headers[0]]):{lengths[0]}}")
        for header, length in zip(headers[1:], lengths[1:]):
            sys.stdout.write(f" | {str(item[header]):{length}}")

    sys.stdout.write("\n")
    sys.stdout.flush()


def print_results(args, ttys):
    """
    Print the given TTY devices according to the given args
    """
    if len(args.format) == 1:
        if args.format[0] == "json":
            print(json.dumps(ttys, indent=2))
            return

        if args.format[0] == "table":
            for tty in ttys:
                tty["ctime"] = time.strftime("%H:%M:%S",
                                             time.localtime(tty["ctime"]))
            headers = ["path", "driver", "vendor", "model", "model_db",
                       "serial", "ctime", "iface_num"]
            print_table(ttys, headers)
            return

    for tty in ttys:
        line = ""
        for fmt in args.format:
            item = tty[fmt]
            if item.rfind(args.format_sep) >= 0:
                # item contains separator --> quote it
                # using json.dumps to also escape quotation chars and other
                # unsafe stuff
                item = json.dumps(item)
            line += f"{args.format_sep}{item}"
        print(line[len(args.format_sep):])


def generate_filters(args):
    """
    Generate filters for use in the filters_match function from the command
    line arguments
    """
    result = []
    if args.serial is not None:
        result.append(("serial", re.compile(r"^" + re.escape(args.serial)
                       + r"$")))

    if args.driver is not None:
        result.append(("driver", re.compile(args.driver)))

    if args.model is not None:
        result.append(("model", re.compile(args.model)))

    if args.model_db is not None:
        result.append(("model_db", re.compile(args.model_db)))

    if args.vendor is not None:
        result.append(("vendor", re.compile(args.vendor)))

    if args.vendor_db is not None:
        result.append(("vendor_db", re.compile(args.vendor_db)))

    if args.iface_num is not None:
        result.append(("iface_num", re.compile(args.iface_num)))

    return result


def print_ttys(args):
    """
    Print ttys as specified by the given command line arguments
    """
    args = parse_args(args)
    filters = generate_filters(args)

    ttys = []
    for dev in pyudev.Context().list_devices(subsystem='tty', ID_BUS='usb'):
        tty = tty2dict(dev)
        if tty["serial"] not in args.exclude_serial and filters_match(filters, tty):
            ttys.append(tty)

    if args.most_recent:
        if len(ttys) > 0:
            most_recent = ttys[0]
            for tty in ttys:
                if tty["ctime"] > most_recent["ctime"]:
                    most_recent = tty
            ttys = [most_recent]
        else:
            ttys = []

    if len(ttys) == 0:
        sys.exit(1)

    print_results(args, ttys)


if __name__ == "__main__":
    print_ttys(sys.argv)
