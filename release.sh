#!/bin/sh
# Nico Schottelius, 2021-12-17

current=$(git describe --dirty)
last_tag=$(git describe --tags --abbrev=0)
registry=harbor.ungleich.svc.p10.k8s.ooo/ungleich-public
image_url=$registry/dynamicweb:${current}

if echo $current | grep -q -e 'dirty$'; then
    echo Refusing to release a dirty tree build
    exit 1
fi

if [ "$current" != "$last_tag" ]; then
    echo "Last tag ($last_tag) is not current version ($current)"
    echo "Only release proper versions"
    exit 1
fi

docker tag dynamicweb:${current} ${image_url}
docker push ${image_url}
