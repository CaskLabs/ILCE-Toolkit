# Publishing ILCE Toolkit

The public release repository is `CaskLabs/ILCE-Toolkit`. The Homebrew cask lives
in `CaskLabs/tap`, at `Casks/ilce-toolkit.rb`.

1. Update `CFBundleShortVersionString` and `CFBundleVersion` in `pmca-gui.spec`.
   Use a three-part version such as `0.1.0`. Update `.github/RELEASE_NOTES.md`.
2. Run the desktop tests, commit the changes and push the default branch.
3. Tag that commit with the matching version and push the tag:

   ```bash
   git tag -a v0.1.0 -m "ILCE Toolkit 0.1.0"
   git push origin v0.1.0
   ```

4. The desktop workflow tests, builds, verifies the frozen worker (including
   installer TLS AES) and publishes the ZIP and `SHA256SUMS` after success.
   The tag version must match the app's bundle version. Release publishing uses
   the repository's `GITHUB_TOKEN`; no Apple signing secrets are needed.
5. Download the release ZIP and `SHA256SUMS`, then verify the checksum. Update
   the cask's `version` and `sha256` to match the published archive. Its URL is
   `https://github.com/CaskLabs/ILCE-Toolkit/releases/download/v#{version}/ILCE-Toolkit-#{version}-macos-arm64.zip`.
6. Run `brew style --cask ilce-toolkit` and `brew audit --cask ilce-toolkit` in a
   checkout of the tap, then commit and push the cask update. Test downloading
   and installing the published cask before announcing the release.

For local packaging after `python tools/build_macos.py` and
`python tools/check_bundle.py`, run `python tools/package_macos.py --version 0.1.0`.

Releases are ad hoc signed and not notarized. This keeps distribution possible
without a paid Apple developer account. macOS users may need to approve the app
under **System Settings → Privacy & Security → Open Anyway** after their first
launch attempt. Keep this information in the README, release notes and cask
caveats. No installer step disables Gatekeeper or removes quarantine attributes.
