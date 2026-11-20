# Chinese Localization

GalaxyCTR can draw its text in Chinese. The translation is not in this repository and not in
the builder: it comes from a fan localization pack for the Japanese disc, which the player
already has. The port itself only needed two changes for this: on a Japanese disc it asks the
game for Japanese assets ([`sc.cpp`](../platform/3ds/rvl/sc.cpp)), and it names the file it
could not find when a resource is missing ([`FileRipper.cpp`](../src/Game/System/FileRipper.cpp)).

## What a pack contains

A pack is a Riivolution overlay for `RMGJ01`: archives under `iQue/files/`, plus `sys/main.dol`,
`opening.bnr` and the Wii HOME Menu resources, which the 3DS port does not use. Packs in the
wild also ship a `Digital Hearts` tree, a different fan revision; this tool reads only `iQue`.

## Applying it

Build the game from your own Japanese disc first, then apply the pack to the converted folder:

```sh
python3 tools/3ds/apply_ique_patch.py --patch SMG-CNzh11_5.zip \
    --base /path/to/smg --out /path/to/smg-cn
```

`--base` is the converted tree the builder made (the folder holding `files/`, `native/` and
`port/`), and `--out` is a new folder; the source is left as it was.

The tool converts every archive of the pack for the 3DS, writes them into the copy, rebuilds
the file cache (`sdmc:/smg/cache`) and reads every applied archive back out of the cache. A
mismatch stops it, so a half-applied overlay cannot reach the console. `localization-manifest.json`
in the output lists each archive with the SHA-256 of the pack's file and of the converted one.

Two archives are skipped on purpose: `JpJapanese/LayoutData/HomeButton.arc` is a U8 archive,
which the port does not read, and the Wii HOME Menu is not ported.

## Copying to the console

Replace `sdmc:/smg/files` and `sdmc:/smg/cache` with the ones the tool wrote. `native/`,
`port/` and `nand/` stay as they are: the models and the saved games are the same.

The packed cache holds files up to 2 MB, so a larger localized archive (the particle effect
archive is) stays on the card and must be copied with `files/`.
