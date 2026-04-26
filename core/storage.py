"""
Custom static-files storage classes.

NonStrictManifestStaticFilesStorage is a hardened version of WhiteNoise's
CompressedManifestStaticFilesStorage that:

  1. Skips post-processing of JS files for `//# sourceMappingURL=...` rewrites.
     Vendor minified bundles (chart.min.js, alpine.min.js, htmx.min.js) point
     to .map files we don't ship. Default WhiteNoise tries to rewrite those
     references to hashed equivalents, fails with MissingFileError, and aborts
     collectstatic. We don't need source maps in production, so we drop the
     JS post-process pattern entirely.

  2. Sets manifest_strict = False as a belt-and-braces measure for missing
     references at request-time.

CSS post-processing (url(...), @import, sourceMappingURL) is preserved —
none of our CSS references unresolved files.
"""
from django.contrib.staticfiles.storage import HashedFilesMixin
from whitenoise.storage import CompressedManifestStaticFilesStorage


class NonStrictManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """Tolerates missing source-map references in vendored JS bundles."""

    manifest_strict = False

    # Override patterns: keep CSS rules, drop JS rules. Files are still
    # content-hashed and served cache-busted; only the *intra-file* URL
    # rewriting is skipped for JS.
    patterns = (
        ("*.css", HashedFilesMixin.patterns[0][1]),
    )
