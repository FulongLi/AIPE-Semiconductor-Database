# Licensing and data rights

The starting repository did not include a top-level license. This refactor does not
assign a new blanket license to historical contributions or manufacturer data.
Repository-owner selection of a code license and confirmation of historical rights
remain outstanding. Package metadata intentionally does not claim an SPDX license.

The retired `transistor.py` appeared substantially inherited from UPB-LEA's
`transistordatabase`, as identified in the refactor request. Its imports depend on
that absent package. It has been removed from the V3 working tree; no implementation
from that monolith was copied into the new package. Its history is not relicensed or
erased. Prior distribution and attribution questions are not resolved by this removal.

Original Wolfspeed XML comments, disclaimers and the manufacturer model guide remain
byte-identical in `data/raw/`. Their rights are independent of AIPE's Python code.
Source metadata identifies the manufacturer and leaves unknown license, redistribution
and commercial-use permissions as null; public visibility is not a grant of reuse
rights. Normalization does not change underlying data rights.

`AccessMetadata` supports owner, license, redistribution permission, commercial-use
permission, visibility and manufacturer/AIPE/partner/licensed/customer categories.
Partners should supply these explicitly. It is metadata, not an authorization system.
