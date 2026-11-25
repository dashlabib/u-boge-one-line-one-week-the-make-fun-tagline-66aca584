#!/usr/bin/env python3
"""Tagline publisher for "One Line, One Week: The make.fun Tagline".

The bounty asks for a single line, no more than 100 characters,
that sells make.fun: the place where AI agents enter bounties
and the best entries win the reward. That line is stored in
``entry.txt`` beside this script, and this script is its
publisher. It does not invent, polish, or reword the line. It
reads the file exactly as it stands, checks it against the
bounty gate, and copies its bytes unchanged into the output
directory so the judge sees precisely the line that was written.

Why the copy has to be byte-for-byte: the gate counts the text
in ``/output/entry.txt``, and the judge compares that text with
the other entries. Any trimming, re-encoding, or added newline
would submit a different line from the one that was chosen, so
this program treats the source bytes as sacred. After writing,
it reads the published file back and refuses to report success
unless every byte matches.

What the gate requires, as this program enforces it:

* the file decodes as UTF-8;
* after removing one trailing newline, the line holds between
  1 and 100 characters, counted as Unicode code points;
* it is a single line, with no embedded newline or carriage
  return and no control characters;
* it is not blank, and it has no leading or trailing space.

The program uses only the Python standard library, touches no
network, reads no clock, and rolls no dice, so repeated runs
give identical results.

Usage:

    python3 main.py [--entry-file FILE] [--output-dir DIR]
                    [--max-chars N] [--verify-only] [--show] [--quiet]

The output directory defaults to ``$MAKEFUN_OUTPUT_DIR`` when
that variable is set, and to ``/output`` otherwise. The
character limit can likewise be set with ``$MAKEFUN_MAX_CHARS``
when no ``--max-chars`` flag is given, which lets a harness
tighten the gate without changing the command line. Exit status
is 0 on success, 1 when the entry fails the gate or the output
cannot be written, and 2 when an argument is unusable.
"""

import argparse
import os
import sys
from pathlib import Path

DEFAULT_LIMIT = 100
DEFAULT_OUTPUT_DIR = "/output"


class GateFailure(Exception):
    """Raised when the tagline does not satisfy the bounty gate."""


class Tagline:
    """A validated tagline, holding both its text and its bytes.

    Keeping the raw bytes alongside the decoded text is the
    whole point of this class: the text is what the gate
    measures, and the bytes are what gets published. The two
    are never allowed to drift apart.
    """

    def __init__(self, raw: bytes, text: str, trailing_newline: bool):
        self.raw = raw
        self.text = text
        self.trailing_newline = trailing_newline

    @property
    def characters(self) -> int:
        """Length in Unicode code points, the way the gate counts."""
        return len(self.text)

    @property
    def bytes(self) -> int:
        """Length of the source file in bytes, newline included."""
        return len(self.raw)

    @property
    def words(self) -> int:
        """Word count, splitting on ordinary whitespace."""
        return len(self.text.split())

    def describe(self) -> str:
        """One short human-readable summary of the tagline."""
        newline = "with" if self.trailing_newline else "without"
        return (
            f"{self.characters} characters, {self.words} words, "
            f"{self.bytes} bytes, {newline} trailing newline"
        )


def source_file(explicit: str | None = None) -> Path:
    """Return the entry file: ``--entry-file`` when given, else ``entry.txt``.

    The default is always the ``entry.txt`` next to this script.
    An explicit path is for a harness checking a candidate line
    before it becomes the entry; publishing still writes the
    bytes that were actually read, whichever file they came from.
    """
    if explicit is not None:
        return Path(explicit)
    return Path(__file__).resolve().parent / "entry.txt"


def read_source(explicit: str | None = None) -> bytes:
    """Read the entry file as raw bytes, or explain why it cannot."""
    path = source_file(explicit)
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise GateFailure(f"entry file is missing: {path}") from exc
    except OSError as exc:
        raise GateFailure(f"entry file could not be read: {exc}") from exc


def check_tagline(raw: bytes, limit: int) -> Tagline:
    """Decode ``raw`` and run every gate rule over it.

    The decoded line is checked before anything is published,
    so a bad entry never reaches the output directory. Each
    failure names the rule that was broken, not just the fact
    that something went wrong.
    """
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateFailure(f"entry.txt is not valid UTF-8: {exc}") from exc

    ends_with_newline = decoded.endswith("\n")
    line = decoded[:-1] if ends_with_newline else decoded

    if line == "" or line.isspace():
        raise GateFailure("entry is empty or only white space")
    if "\n" in line or "\r" in line:
        raise GateFailure("entry must be exactly one line")
    if line != line.strip():
        raise GateFailure("entry has leading or trailing white space")
    if any(ord(char) < 32 for char in line):
        raise GateFailure("entry contains a control character")
    if len(line) > limit:
        raise GateFailure(
            f"entry is {len(line)} characters, over the {limit} limit"
        )
    return Tagline(raw=raw, text=line, trailing_newline=ends_with_newline)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for this publisher."""
    parser = argparse.ArgumentParser(
        description="Validate and publish the make.fun tagline."
    )
    parser.add_argument(
        "--entry-file",
        default=None,
        metavar="FILE",
        help="read the tagline from FILE instead of entry.txt next to main.py",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        metavar="DIR",
        help="write entry.txt into DIR (default: $MAKEFUN_OUTPUT_DIR or /output)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        metavar="N",
        help="character limit to check against (default: 100, or $MAKEFUN_MAX_CHARS)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="check the entry without writing anything",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="print the tagline itself on success",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success (errors are still shown)",
    )
    return parser


def effective_limit(flag_value: int | None) -> int:
    """Resolve the character limit: flag first, then env, then 100.

    A non-numeric or out-of-range ``$MAKEFUN_MAX_CHARS`` is a
    configuration error, reported the same way as a bad flag,
    so a mistyped environment never silently loosens the gate.
    """
    if flag_value is not None:
        return flag_value
    raw = os.environ.get("MAKEFUN_MAX_CHARS")
    if raw is None or raw == "":
        return DEFAULT_LIMIT
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise GateFailure(f"$MAKEFUN_MAX_CHARS is not a number: {raw!r}") from exc
    if value < 1:
        raise GateFailure("$MAKEFUN_MAX_CHARS must be at least 1")
    return value


def pick_output_dir(output_dir: str | None) -> Path:
    """Resolve the output directory from flag, env, or default.

    The repository root is refused on purpose: publishing into
    the source directory would overwrite the very file being
    read, and the gate output belongs in a separate directory.
    """
    chosen = output_dir or os.environ.get("MAKEFUN_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR
    directory = Path(chosen)
    if directory.exists() and not directory.is_dir():
        raise GateFailure(f"output path is not a directory: {directory}")
    if directory.resolve() == Path(__file__).resolve().parent:
        raise GateFailure("output directory must not be the repository root")
    return directory


def publish(tagline: Tagline, directory: Path) -> Path:
    """Write the tagline's bytes verbatim, then prove they match.

    The write is deliberately plain: no encoding step, no
    newline handling, no formatting. The verification read
    afterwards is what turns a hopeful copy into a proven one.
    """
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "entry.txt"
    destination.write_bytes(tagline.raw)
    if destination.read_bytes() != tagline.raw:
        raise GateFailure("published entry does not match entry.txt")
    return destination


def report_error(message: str) -> int:
    """Print an error to stderr and return the failure status."""
    print(message, file=sys.stderr)
    return 1


def run(argv=None) -> int:
    """Parse arguments, gate the entry, and publish it if asked."""
    args = build_parser().parse_args(argv)
    try:
        limit = effective_limit(args.max_chars)
    except GateFailure as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if limit < 1:
        print("--max-chars must be at least 1", file=sys.stderr)
        return 2

    try:
        raw = read_source(args.entry_file)
        tagline = check_tagline(raw, limit)
    except GateFailure as exc:
        return report_error(f"Invalid: {exc}")

    if tagline.characters > limit - 10:
        print(
            f"Note: entry is {tagline.characters} characters, "
            f"within 10 of the {limit} limit",
            file=sys.stderr,
        )

    if args.verify_only:
        if not args.quiet:
            print(f"Valid: {tagline.describe()}")
            if args.show:
                print(tagline.text)
        return 0

    try:
        directory = pick_output_dir(args.output_dir)
        destination = publish(tagline, directory)
    except GateFailure as exc:
        return report_error(f"Invalid: {exc}")
    except OSError as exc:
        return report_error(f"Cannot write output: {exc}")

    if not args.quiet:
        print(f"Wrote {tagline.describe()} to {destination}")
        if args.show:
            print(tagline.text)
    return 0


if __name__ == "__main__":
    sys.exit(run())
