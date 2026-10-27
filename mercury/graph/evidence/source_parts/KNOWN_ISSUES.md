# Known issues

These findings from commit `d4e4ffc` are recorded for further examination. IDs remain stable when entries are updated.

## XML-001 - Missing Markdown output is treated as ready

- Status: Open
- Severity: P2
- Location: [xml_build.py](xml_build.py), `build_xml_markdown()` and `open_xml_catalogue()`
- Description: Build reuse checks the source stamp and catalogue readiness without verifying the Markdown output. After a
  successful conversion, deleting the destination while retaining its sibling build directory causes the next build to create
  an empty destination, skip conversion, and report success. A SourceMaker accepts the catalogue as ready, but requesting a
  missing page returns `FILE_NEEDS_UPDATE`. Repeated builds do not regenerate the missing output.

## XML-002 - Rebuilding preserves stale cached documents

- Status: Open
- Severity: P2
- Location: [source_maker.py](source_maker.py), `_build_xml_indices()` and `_xml_file()`
- Description: The SourceMaker file cache survives rebuilding. Load and parse a document, change its XML content, and call
  `build_indices()` on the same maker. Conversion updates the Markdown file, but subsequent requests return the cached
  SourceFile. Its ready state preserves the previous content and section indices instead of loading the updated document.

## XML-003 - Changing cluster size invalidates existing readers

- Status: Open
- Severity: P2
- Location: [xml_build.py](xml_build.py), `open_xml_catalogue()`
- Description: Opening a destination with a different cluster size changes the shared database assignments in place. Existing
  catalogue instances retain their cached size and derive their index trees using that previous size. For five pages, opening
  one catalogue with size 2 and another with size 3 leaves the first reader expecting a third leaf cluster that no longer holds
  any pages. Existing readers can consequently return misplaced pages or fail to resolve previously valid indices.

## XML-004 - Interrupted reclustering leaves inconsistent assignments

- Status: Open
- Severity: P2
- Location: [xml_catalogue.py](xml_catalogue.py), `recluster()`
- Description: Reclustering commits page assignments in chunks of 100,000 while retaining the ready flag. The recorded cluster
  size changes only after every chunk finishes. Interruption after a chunk commits can leave a mixture of old and new
  assignments. Reopening with the previously recorded size skips reclustering and accepts the inconsistent catalogue as ready.

## XML-005 - Case-distinct titles abort conversion

- Status: Open
- Severity: P2
- Location: [xml_conversion.py](xml_conversion.py), `collision_key()`
- Description: Collision keys always use Unicode normalization and case folding, and the catalogue requires those keys to be
  unique. An export containing titles such as `Iphone` and `IPhone` is rejected before any page is converted, even on storage
  that supports both filenames. Existing tests explicitly expect this rejection. Examine whether the portability policy should
  depend on destination filesystem semantics or use disambiguated filenames to support exports containing both titles.
