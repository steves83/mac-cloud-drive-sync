# Mac Cloud Drive Sync

A free personal macOS bridge using MIT-licensed [rclone](https://rclone.org/) to sync ordinary iCloud Drive files with Google My Drive. The Python runner and native macOS launcher are provided under the MIT license.

This repository includes only source code and public app information. It deliberately does not include OAuth credentials, user settings, synchronization inventories, documents, or logs. The runner expects a private local configuration under `~/Library/Application Support/CloudDriveSync`.

[App information](https://steves83.github.io/mac-cloud-drive-sync/) · [Privacy policy](https://steves83.github.io/mac-cloud-drive-sync/privacy.html)

## No automatic deletions

The automatic runner uses `rclone copy` in both directions, never `sync`, `bisync`, `delete`, `purge`, or `move`. Missing files are restored from the other side. Replaced versions are stored inside cloud recovery folders and recovery history is copied to both clouds without cleanup. Old names remain after renaming. Actual cloud file removal requires separate explicit permission.
