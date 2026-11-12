# RR Foods reference-layout correction

- Corrected the desktop customer header to remain on one row at 1100px and wider; the old `sh__br` flex-basis rule was forcing the search and actions onto a second row.
- Kept the mobile centered logo, menu, notification, search overlay, favourites and cart; hid text labels and lower-priority track/account icons on narrow phones (those links remain in the drawer).
- Added responsive compact sizing for 1100–1279px and a 320px-safe icon layout.
- Changed the carousel's no-image fallback to a green grocery palette and updated CSS query versions to avoid stale browser/Render cache.

Deploy the ZIP to Render and hard-refresh the browser (Ctrl+Shift+R). The live banner still needs a valid banner image URL configured in the Admin carousel; the CSS gradient is a fallback, not a replacement for the grocery photo in the reference design.
