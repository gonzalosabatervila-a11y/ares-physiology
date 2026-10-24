# ARES independent CI and immutable image design

ARES remains an independent repository. Every pull request runs the complete offline suite
and builds the container without publishing it. Only a merge to `master` may publish an OCI
image. The image contains the exact source commit as an OCI revision label and is consumed by
GonzaloOS only through an immutable registry digest. ARES never deploys itself and receives no
production credential.

Automatic stable deployment is a later stage and remains disabled until GonzaloOS staging has
demonstrated encrypted backup restoration and rollback.
