#!/usr/bin/python

# git-tbdiff: show the difference between two versions of a topic branch
#
# Copyright (c) 2013, Thomas Rast <trast@inf.ethz.ch>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import hungarian # https://pypi.python.org/pypi/hungarian
import tempfile
import subprocess
import difflib
import numpy as np
import optparse

parser = optparse.OptionParser()
parser.add_option('--color', default=True, action='store_true', dest='color')
parser.add_option('--no-color', action='store_false', dest='color')
parser.add_option('--creation-weight', action='store',
                  dest='creation_fudge', type=float, default=0.6,
                  help='Fudge factor by which creation is weighted [%default]')

def die(msg):
    print >>sys.stderr, msg
    sys.exit(1)

def strip_uninteresting_patch_parts(lines):
    out = []
    state = 'head'
    for line in lines:
        if line.startswith('diff --git'):
            state = 'diff'
            out.append('\n')
            out.append(line)
        elif state == 'head':
            if line.startswith('Author: '):
                out.append(line)
                out.append('\n')
            elif line.startswith('    '):
                out.append(line)
        elif state == 'diff':
            if line.startswith('index '):
                pass # skip
            elif line.startswith('@@ '):
                out.append('@@\n')
            else:
                out.append(line)
            continue
    return out

def read_patches(rev_list_arg):
    series = []
    diffs = {}
    p = subprocess.Popen(['git', 'log', '-p', '--no-merges', '--reverse', '--date-order',
                          rev_list_arg],
                         stdout=subprocess.PIPE)
    sha1 = None
    data = []
    def handle_commit():
        if sha1 is not None:
            series.append(sha1)
            diffs[sha1] = strip_uninteresting_patch_parts(data)
            del data[:]
    for line in p.stdout:
        if line.startswith('commit '):
            handle_commit()
            _, sha1 = line.strip().split()
            continue
        data.append(line)
    handle_commit()
    p.wait()
    return series, diffs


def strip_to_diff_parts_1(lines):
    in_diff = False
    for line in lines:
        if line.startswith('diff --git'):
            in_diff = True
        if not in_diff:
            continue
        if line.startswith('@@ '):
            continue
        yield line
def strip_to_diff_parts(*args, **kwargs):
    return list(strip_to_diff_parts_1(*args, **kwargs))


def diffsize(lA, lB):
    if not lA:
        return len(strip_to_diff_parts(lB))
    if not lB:
        return len(strip_to_diff_parts(lA))
    lA = strip_to_diff_parts(lA)
    lB = strip_to_diff_parts(lB)
    diff = difflib.unified_diff(lA, lB)
    return len(list(diff))


def commitinfo(sha1, fmt=None):
    return subprocess.check_output(['git', 'log', '--no-walk', '--pretty=format:%h %s', sha1]).strip().split(' ', 1)



c_reset = ''
c_commit = ''
c_frag = ''
c_old = ''
c_new = ''

def get_color(varname, default):
    return subprocess.check_output(['git', 'config', '--get-color', varname, default])

def load_colors():
    global c_reset, c_commit, c_frag, c_new, c_old
    c_reset = get_color('', 'reset')
    c_commit = get_color('color.diff.commit', 'yellow dim')
    c_frag = get_color('color.diff.frag', 'magenta')
    c_old = get_color('color.diff.old', 'red')
    c_new = get_color('color.diff.new', 'green')

def commitinfo_maybe(cmt):
    if cmt:
        sha, subj = commitinfo(cmt)
    else:
        sha = 7*'-'
        subj = ''
    return sha, subj

def format_commit_line(i, left, j, right, has_diff=False):
    left_sha, left_subj = commitinfo_maybe(left)
    right_sha, right_subj = commitinfo_maybe(right)
    assert left or right
    if left and not right:
        color = c_old
        status = '<'
    elif right and not left:
        color = c_new
        status = '>'
    elif has_diff:
        color = c_commit
        status = '!'
    else:
        color = c_commit
        status = '='
    fmt = '%s' # color
    args = [color]
    # left coloring
    if status == '!':
        fmt += c_reset + c_old
    # left num
    fmt += numfmt if left else numdash
    args += [i+1] if left else []
    # left hash
    fmt += ": %8s"
    args += [left_sha]
    if status == '!':
        fmt += c_reset + color
    # middle char
    fmt += " %s "
    args += [status]
    # right coloring
    if status == '!':
        fmt += c_reset + c_new
    # right num
    fmt += numfmt if right else numdash
    args += [j+1] if right else []
    # right hash
    fmt += ": %8s"
    args += [right_sha]
    if status == '!':
        fmt += c_reset + color
    # subject
    fmt += " %s"
    args += [right_subj if right else left_subj]
    #
    fmt += "%s"
    args += [c_reset]
    print fmt % tuple(args)

def compute_assignment(sA, dA, sB, dB):
    la = len(sA)
    lb = len(sB)
    dist = np.zeros((la+lb, la+lb), dtype=np.uint32)
    for i,u in enumerate(sA):
        for j,v in enumerate(sB):
            dist[i,j] = diffsize(dA[u], dB[v])
    # print dist
    for i,u in enumerate(sA):
        for j in range(lb, lb+la):
            dist[i,j] = options.creation_fudge*diffsize(dA[u], None)
    for i in range(la, la+lb):
        for j,v in enumerate(sB):
            dist[i,j] = options.creation_fudge*diffsize(None, dB[v])
    lhs, rhs = hungarian.lap(dist)
    numwidth = max(len(str(la)), len(str(lb)))
    numfmt = "%%%dd" % numwidth
    numdash = numwidth*'-'
    # We assume the user is really more interested in the second
    # argument ("newer" version).  To that end, we print the output in
    # the order of the RHS.  To put the LHS commits that are no longer
    # in the RHS into a good place, we place them once we have seen
    # all of their predecessors in the LHS.
    new_on_lhs = (lhs >= lb)[:la]
    lhs_prior_counter = np.arange(la)

    def process_lhs_orphans():
        while True:
            assert (lhs_prior_counter >= 0).all()
            w = (lhs_prior_counter == 0) & new_on_lhs
            idx = w.nonzero()[0]
            if len(idx) == 0:
                break
            format_commit_line(idx[0], sA[idx[0]], None, None)
            new_on_lhs[idx[0]] = False
            lhs_prior_counter[idx[0]+1:] -= 1

    for j,(u,i) in enumerate(zip(sB, rhs)):
        # now show an RHS commit
        process_lhs_orphans()
        if i < la:
            idiff = list(difflib.unified_diff(dA[sA[i]], dB[u]))
            if idiff:
                format_commit_line(i, sA[i], j, u, has_diff=True)
                for line in idiff[2:]: # starts with --- and +++ lines
                    c = ''
                    if line.startswith('+'):
                        c = c_new
                    elif line.startswith('-'):
                        c = c_old
                    elif line.startswith('@@'):
                        c = c_frag
                    print "    %s%s%s" % (c, line.rstrip('\n'), c_reset)
                print
            else:
                format_commit_line(i, sA[i], j, u)
            lhs_prior_counter[i+1:] -= 1
        else:
            format_commit_line(None, None, j, u)
    process_lhs_orphans()


if __name__ == '__main__':
    options, args = parser.parse_args()
    if options.color:
        load_colors()
    if len(args) != 2:
        die("usage: %s A..B C..D" % sys.argv[0])
    sA, dA = read_patches(args[0])
    sB, dB = read_patches(args[1])
    compute_assignment(sA, dA, sB, dB)
