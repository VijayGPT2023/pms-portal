"""
Custom static-files storage classes.

NonStrictManifestStaticFilesStorage tolerates missing JS source-map references.
The minified vendor bundles we ship (chart.min.js, alpine.min.js, htmx.min.js)
end with //# sourceMappingURL=...js.map comments. WhiteNoise's default
CompressedManifestStaticFilesStorage parses these and fails hard if the .map
file isn't present, blocking collectstatic.

We don't need source maps in production (they're only useful when debugging
unminified code in the browser), so the safe path is to set
manifest_strict = False — WhiteNoise then logs warnings for missing references
but still completes collectstatic and serves the page correctly.
"""
from whitenoise.storage import CompressedManifestStaticFilesStorage


class NonStrictManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """Tolerates missing source maps in vendored JS bundles."""
    manifest_strict = False
