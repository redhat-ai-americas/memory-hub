package static

import (
	"embed"
	"io/fs"
)

//go:embed index.html style.css app.js
var content embed.FS

// Files returns the embedded static file system.
func Files() fs.FS {
	return content
}
