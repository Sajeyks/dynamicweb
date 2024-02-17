#!/bin/sh

if [ $# -lt 1 ]; then
    echo "$0 imageversion [push]"
    echo "If push is specified, also push to our harbor"
    exit 1
fi

tagprefix=harbor.k8s.ungleich.ch/ungleich-public/dynamicweb
version=$1; shift

tag=${tagprefix}:${version}

docker build -t "${tag}" .
