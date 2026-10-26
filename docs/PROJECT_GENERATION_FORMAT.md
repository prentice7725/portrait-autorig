# Rig Project save generations

Rig Project writers use an append-only generation folder so a save can be
validated before it becomes the active project state. Existing projects without
`project-generation.json` remain readable; their first successful save creates
the generation structure.

## Layout and commit record

Each completed save is stored under `project_generations/<generation>/`. It
contains the project metadata, source reference, generated base manifest and
images, authoring buckets, QA status, and resolved runtime manifest. Its
`complete.json` records the generation ID, creation time, and SHA-256 digest of
every payload file.

The root `project-generation.json` has the same record as `complete.json`. It is
the commit pointer and is published only after all generation files have been
written and checked. Loaders verify the pointer, completion record, and file
digests before accepting a generation. A corrupt or incomplete committed
generation produces an error instead of loading mixed files as defaults.

## Compatibility files and interruption recovery

The root `project.json`, `source/`, `generated/`, `authoring/`, `qa/`, and
`portrait_rig_manifest.json` remain available for existing tools. Writers update
these compatibility files after committing the generation, with the runtime
manifest written last. Each individual file uses a same-filesystem temporary
file and atomic replacement in Python; the browser writer closes each
FileSystem Access writable before moving to the next file. The project as a
whole does not rely on a multi-file rename.

If the process stops during compatibility export, the previous root runtime
manifest remains a complete export until the new manifest is replaced. The
generation pointer remains authoritative for Rig Studio. Opening the project
checks the compatibility files and retries the export from the committed
generation. Other tools that only read the root runtime manifest continue to
see a complete older or newer manifest and its referenced images.

The filesystem guarantees still depend on the operating system, filesystem,
browser, and device. Python flushes file data and uses `os.replace`; directory
flushes are used where the host supports them and are skipped on Windows.
Browser close and atomic replacement guarantees are per file, not across the
whole folder. The generation record detects incomplete or corrupted files; it
does not promise hardware-level durability after sudden power loss.

## Version boundaries

The generation record version describes this commit/checksum envelope. It is
separate from the Rig Project JSON schema version, authoring schema version,
source revision, and runtime manifest contract. The source revision continues
to identify source inputs; generation checksums identify one saved project
snapshot. Loaders do not migrate or rewrite projects with an unsupported
project schema version.
