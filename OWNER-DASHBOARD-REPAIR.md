# Owner dashboard template repair

Fixed `app/templates/owner/dashboard.html`.

The template previously put a full inventory-intelligence section inside both the `title` and `heading` blocks. Those blocks are rendered in the document title and top header, so this duplicated/misplaced dashboard markup and displaced the actual dashboard content. The title and heading blocks now contain only their intended text; the full dashboard remains in the content block.

No database migration is needed.
