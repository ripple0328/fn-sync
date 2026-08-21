# FN sync for Omarchy

This bundle contains the `fn-sync` pacman package and the matching
`community.fnos-sync` Omarchy plugin.

From this extracted directory, run the installer as your normal desktop user:

```sh
./scripts/install-omarchy-bundle.sh
```

The installer asks Omarchy/pacman to install the runtime dependencies, installs
the locally built pacman artifact with `sudo pacman -U`, copies the plugin into
your user configuration, enables the user service, and enables the right-side
bar widget. Do not run the whole installer with `sudo`.

The package does not delete sync configuration, credentials, or synchronized
files when it is removed.
