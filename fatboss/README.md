# FatBoss cgame for ET: Legacy

Fork of [ET: Legacy](https://github.com/etlegacy/etlegacy) (GPLv3) used by the
Poland ET Legacy gather servers. Only the client game module (cgame) changes;
the server keeps running the official legacy mod.

- `src/cgame/cg_fatboss.c`: FatBoss additions (`+ilookatweapon` weapon inspect).
- `.github/workflows/fatboss.yml`: builds the cgame for every client platform and
  publishes `zzz_fatboss_<VERSION>.pk3` as a release.
- `fatboss/VERSION`: the pk3 name suffix. Change it on every release, because
  clients cache pk3 files by name.

The branch `fatboss` is based on the exact ET: Legacy version the servers run
(currently v2.86.0). When the servers move to a new ET: Legacy version, rebase
this branch onto that tag and publish a new pk3 before updating the servers.
