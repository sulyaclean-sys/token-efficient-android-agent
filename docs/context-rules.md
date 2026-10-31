# Round-trip economy for agents

Measured on a mid-size session (a few hundred KB of conversation): the *content*
returned by a tool call is rarely the cost driver. Re-sending the whole
conversation is. So:

> **Round-trips are the currency. Bytes are rounding error.**

## Rules

1. **One search call, many queries.** A search tool that accepts an array should
   receive every question at once. Five separate searches = five full re-sends.
2. **Batch shell work.** Independent read-only commands belong in one batched
   call (I/O-bound: up to ~8). CPU-bound or stateful commands (tests, builds,
   anything binding a port or taking a lock): keep at 1, or they will race.
3. **Print conclusions, not transcripts.** End every command with the filter that
   turns 10,000 lines into 3: `grep -c`, `awk`, `head -c 200`, a tiny script. If
   the answer may exceed a few KB, index it instead of printing it.
4. **Assume each batched command is its own shell.** `cd` and `export` do not
   survive to the next command; write absolute paths in every line or join steps
   with `&&`.
5. **Temp directories are not shared between tools.** A file written to a temp dir
   by one tool is invisible to another. Pass files through a real, shared path.
6. **Index once, query many times.** If a document must be consulted rev / later,
   put it in the searchable index once, then query it - do not re-fetch, and do not
   re-read it into the transcript "just to check".
7. **Do not use a search tool as grep, or a reader as a parser.** Searching for
   one known string is cheaper with the file tools; parsing 40 MB is cheaper in
   code.
8. **Never let errors go to stdout unfiltered.** An uncaught exception or a raw
   traceback can dump an entire file into the conversation. Catch, summarise,
   print one line.
9. **Ask what the answer will look like before running the command.** If you
   cannot predict its size, the command is the wrong shape - derive in code and
   print the result.

## When *not* to optimize

* The command's whole output is one short line you intend to read verbatim
  (`pwd`, `git status` on a clean tree). Use the plain shell.
* You need the exact bytes of a response body. That is a transport question;
  use HTTP, not a browsing/extraction tool.
* You already know the answer is on line 3. Read three lines.
* You are editing one file repeatedly. Read + edit; do not index it.

## The decision order

1. Can a plain dump / text answer the question? (no image)
2. Can one command answer it? (no second round-trip)
3. Can one *image* answer all remaining questions? (one read, reused)
4. Only then: more round-trips.
