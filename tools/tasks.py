#!/usr/bin/env python
"""
invoke script for releasing pyzmq

Must be run on macOS with Framework Python from Python.org

usage:

    invoke release 14.3.1

"""

# Copyright (C) PyZMQ Developers
# Distributed under the terms of the Modified BSD License.


from __future__ import print_function

import glob
import os
import platform
import pipes
import re
import shutil
from subprocess import check_output
import sys
import time

from contextlib import contextmanager

from invoke import task, run as invoke_run
import requests

PYZMQ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PYZMQ_ROOT)
from buildutils.bundle import vs as libzmq_vs

libsodium_version = '1.0.18'

pjoin = os.path.join

repo = 'https://github.com/zeromq/pyzmq'
branch = os.getenv('PYZMQ_BRANCH', 'master')

if platform.processor() != 'aarch64' :
    sdkroot = os.getenv("SDKROOT")
    if not sdkroot:
        xcode_prefix = check_output(["xcode-select", "-p"]).decode().strip()
        # 10.9
        sdkroot = os.path.join(xcode_prefix, "Platforms/MacOSX.platform/Developer/SDKs/MacOSX10.9.sdk")
        if os.path.exists(sdkroot):
            os.environ["SDKROOT"] = sdkroot
        else:
            print("SDK not found at %r" % sdkroot)
            time.sleep(10)

# Workaround for PyPy3 5.8
if platform.processor() != 'aarch64' :
    if 'LDFLAGS' not in os.environ:
        os.environ['LDFLAGS'] = '-undefined dynamic_lookup'

# set mac deployment target
if platform.processor() != 'aarch64' :
    if 'MACOSX_DEPLOYMENT_TARGET' not in os.environ:
        os.environ['MACOSX_DEPLOYMENT_TARGET'] = '10.9'

# set compiler env (avoids issues with missing 'gcc-4.2' on py27, etc.)
if 'CC' not in os.environ:
    os.environ['CC'] = 'clang'

if 'CXX' not in os.environ:
    os.environ['CXX'] = 'clang++'

if platform.processor() != 'aarch64' :    
    _framework_py = lambda xy: "/Library/Frameworks/Python.framework/Versions/{0}/bin/python{0}".format(xy)
    py_exes = {
        '3.8' : _framework_py('3.8'),
        '3.7' : _framework_py('3.7'),
        '2.7' : _framework_py('2.7'),
        '3.5' : _framework_py('3.5'),
        '3.6' : _framework_py('3.6'),
        'pypy': "/usr/local/bin/pypy",
        'pypy3': "/usr/local/bin/pypy3",
    }
else:
    py_exes = {
        #'3.8' : "/home/travis/virtualenv/python3.8.0/bin/python",
        '3.7' : "/home/travis/virtualenv/python3.7.5/bin/python",
    }
    
egg_pys = {} # no more eggs!

default_py = '3.7'
# all the Python versions to be built on linux
if platform.processor() != 'aarch64' :
    manylinux_pys = '3.8 3.7 2.7 3.5 3.6'
else:
    manylinux_pys = '3.8 3.7 3.5 3.6'

tmp = "/tmp"
env_root = os.path.join(tmp, 'envs')
repo_root = pjoin(tmp, 'pyzmq-release')
sdist_root = pjoin(tmp, 'pyzmq-sdist')

def _py(py):
    return py_exes[py]

def run(cmd, **kwargs):
    """wrapper around invoke.run that accepts a Popen list"""
    if isinstance(cmd, list):
        cmd = " ".join(pipes.quote(s) for s in cmd)
    kwargs.setdefault('echo', True)
    return invoke_run(cmd, **kwargs)

@contextmanager
def cd(path):
    """Context manager for temporary CWD"""
    cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(cwd)

@task
def clone_repo(ctx, reset=False):
    """Clone the repo"""
    if os.path.exists(repo_root) and reset:
        shutil.rmtree(repo_root)
    if os.path.exists(repo_root):
        with cd(repo_root):
            run("git checkout %s" % branch)
            run("git pull")
    else:
        run("git config --global user.email sakshi.sharma@puresoftware.com")
        run("git config --global user.name sakshi87")
        run("git remote set-url origin https://github.com/zeromq/pyzmq")
        run("git clone %s %s" % (repo, repo_root))

@task
def patch_version(ctx, vs):
    """Patch zmq/sugar/version.py for the current release"""
    major, minor, patch, extra = vs_to_tup(vs)
    version_py = pjoin(repo_root, 'zmq', 'sugar', 'version.py')
    print("patching %s with %s" % (version_py, vs))
    # read version.py, minus VERSION_ constants
    with open(version_py) as f:
        pre_lines = []
        post_lines = []
        lines = pre_lines
        for line in f:
            if line.startswith("VERSION_"):
                lines = post_lines
            else:
                lines.append(line)

    # write new version.py with given VERSION_ constants
    with open(version_py, 'w') as f:
        for line in pre_lines:
            f.write(line)
        f.write('VERSION_MAJOR = %s\n' % major)
        f.write('VERSION_MINOR = %s\n' % minor)
        f.write('VERSION_PATCH = %s\n' % patch)
        f.write('VERSION_EXTRA = "%s"\n' % extra)
        for line in post_lines:
            f.write(line)

@task
def tag(ctx, vs, push=False):
    """Make the tag (don't push)"""
    patch_version(ctx, vs)
    with cd(repo_root):
        run('git commit -a -m "release 22.1.1"'.format(vs))
        run('git tag -a -m "release 22.1.1" v22.1.1'.format(vs))
        if push:
            run('git push --tags')
            run('git push')

def make_env(py_exe, *packages):
    """Make a virtualenv

    Assumes `which python` has the `virtualenv` package
    """
    py_exe = py_exes.get(py_exe, py_exe)

    if not os.path.exists(env_root):
        os.makedirs(env_root)

    env = os.path.join(env_root, os.path.basename(py_exe))
    py = pjoin(env, 'bin', 'python')
    # new env
    if not os.path.exists(py):
        run('virtualenv {} -p {}'.format(
            pipes.quote(env),
            pipes.quote(py_exe),
        ))
        py = pjoin(env, 'bin', 'python')
        run([py, '-V'])
        install(py, 'pip', 'setuptools')
    install(py, *packages)
    return py

def build_sdist(py, upload=False):
    """Build sdists

    Returns the path to the tarball
    """
    with cd(repo_root):
        cmd = [py, 'setup.py', 'sdist']
        run(cmd)
        if upload:
            run(['twine', 'upload', 'dist/*'])

    return glob.glob(pjoin(repo_root, 'dist', '*.tar.gz'))[0]

@task
def sdist(ctx, vs, upload=False):
    clone_repo(ctx)
    tag(ctx, vs, push=upload)
    py = make_env(default_py, 'cython', 'twine', 'certifi')
    tarball = build_sdist(py, upload=upload)
    return untar(tarball)

def install(py, *packages):
    run([py, '-m', 'pip', 'install', '--upgrade'] + list(packages))

def vs_to_tup(vs):
    """version string to tuple"""
    return re.match(r'(\d+)\.(\d+)\.(\d+)\.?([^\.]*)$', vs).groups()

def tup_to_vs(tup):
    """tuple to version string"""
    return '.'.join(tup)

def untar(tarball):
    if os.path.exists(sdist_root):
        shutil.rmtree(sdist_root)
    os.makedirs(sdist_root)
    with cd(sdist_root):
        run(['tar', '-xzf', tarball])

    return glob.glob(pjoin(sdist_root, '*'))[0]

@task
def bdist(ctx, py, wheel=True, egg=False):
    py = make_env(py, 'wheel')
    cmd = [py, 'setup.py']
    if wheel:
        cmd.append('bdist_wheel')
    if egg:
        cmd.append('bdist_egg')
    cmd.append('--zmq=bundled')

    run(cmd)


@task
def manylinux(ctx, vs, upload=False, pythons=manylinux_pys):
    """Build manylinux wheels with Matthew Brett's manylinux-builds"""
    manylinux = '/tmp/manylinux-builds'
    if not os.path.exists(manylinux):
        with cd('/tmp'):
            run("git clone --recursive https://github.com/minrk/manylinux-builds -b pyzmq")
    else:
        with cd(manylinux):
            run("git pull")
            run("git submodule update")
            
    if platform.processor() != 'aarch64' :
        run("docker pull quay.io/pypa/manylinux1_x86_64")
        run("docker pull quay.io/pypa/manylinux1_i686")
    else:
        run("docker pull quay.io/pypa/manylinux2014_aarch64")
    base_cmd = ' '.join([
        "docker",
        "run",
        "--dns=8.8.8.8",
        "--rm",
        "-e",
        "PYZMQ_VERSIONS='{}'".format(vs),
        "-e",
        "PYTHON_VERSIONS='{}'".format(pythons),
        "-e",
        "ZMQ_VERSION='{}'".format(libzmq_vs),
        "-e",
        "LIBSODIUM_VERSION='{}'".format(libsodium_version),
        "-v",
        "$PWD:/io",
    ])

    with cd(manylinux):
        if platform.processor() != 'aarch64' :
            run(base_cmd +  " quay.io/pypa/manylinux1_x86_64 /io/build_pyzmqs.sh")
            run(base_cmd +  " quay.io/pypa/manylinux1_i686 linux32 /io/build_pyzmqs.sh")
        else:
            run(base_cmd +  " quay.io/pypa/manylinux2014_aarch64 /io/build_pyzmqs.sh")
            #with cd('/root/.cache/pip/wheels/cc/d6/c3/3811893eede041ee1275441549ab1296b08833eb5eef478818')
            #unzip pyzmq-19.0.1-cp38-cp38-linux_aarch64.whl
            #ls
    if upload:
        py = make_env(default_py, 'twine')
        run(['twine', 'upload', os.path.join(manylinux, 'wheelhouse', '*')])


@task
def release(ctx, vs, upload=False):
    """Release pyzmq"""
    # Ensure all our Pythons exist before we start:
    for v, path in py_exes.items():
        if not os.path.exists(path):
            raise ValueError("Need %s at %s" % (v, path))
            

    # start from scrach with clone and envs
    clone_repo(ctx, reset=True)
    if os.path.exists(env_root):
        shutil.rmtree(env_root)

    path = sdist(ctx, vs, upload=upload)

    with cd(path):
        for v in py_exes:
            bdist(ctx, v, wheel=True, egg=(v in egg_pys))
        if upload:
            py = make_env(default_py, 'twine')
            run(['twine', 'upload', 'dist/*'])

    manylinux(ctx, vs, upload=upload)
    if upload:
        print("When Travis finished building, upload artifacts with:")
        print("  invoke Travis-artifacts {} --upload".format(vs))


_travis_api = 'https://ci.travis.com/api'
_travis_project = 'minrk/pyzmq'
def _travis_api_request(path):
    """Make an travis API request"""
    r = requests.get('{}/{}'.format(_travis_api, path),
        headers={
            # 'Authorization': 'Bearer %s' % token,
            'Content-Type': 'application/json',
        }
    )
    r.raise_for_status()
    return r.json()


@task
def travis_artifacts(ctx, vs, dest='win-dist', upload=False):
    """Download travis artifacts

    If --upload is given, upload to PyPI
    """
    if not os.path.exists(dest):
        os.makedirs(dest)

    build = _travis_api_request('projects/{}/branch/v{}'.format(_travis_project, vs))
    jobs = build['build']['jobs']
    travis_urls = []
    for job in jobs:
        artifacts = _travis_api_request('buildjobs/{}/artifacts'.format(job['jobId']))
        artifact_urls.extend('{}/buildjobs/{}/artifacts/{}'.format(
            _travis_api, job['jobId'], artifact['fileName']
        ) for artifact in artifacts)
    for url in artifact_urls:
        print("Downloading {} to {}".format(url, dest))
        fname = url.rsplit('/', 1)[-1]
        r = requests.get(url, stream=True)
        r.raise_for_status()
        with open(os.path.join(dest, fname), 'wb') as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)
    if upload:
        py = make_env(default_py, 'twine')
        run(['twine', 'upload', '--skip-existing', '{}/*'.format(dest)])
    else:
        print("You can now upload these wheels with: ")
        print("  twine upload {}/*".format(dest))

