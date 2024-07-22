# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
import re
import yaml
from tcadmin.util.sessions import aiohttp_session, with_aiohttp_session

from ciadmin.generate import tcyml
from ciadmin.generate.ciconfig.projects import Project

_HEAD_REGEX = re.compile(r" symref=HEAD:([^ ]+) ")
_GIT_UPLOAD_PACK_URL = "{repo_base_url}/info/refs?service=git-upload-pack"


async def _get_git_default_branch(project):
    git_url = _GIT_UPLOAD_PACK_URL.format(repo_base_url=project.repo)
    # XXX You must set a git-like user agent otherwise Git http endpoints don't
    # return any data.
    headers = {"User-Agent": "git/mozilla-ci-admin"}
    session = aiohttp_session()
    async with session.get(git_url, headers=headers) as response:
        response.raise_for_status()
        result = await response.text()

    match = _HEAD_REGEX.search(result)
    if match is None:
        raise ValueError(f"{git_url} does not contain data about the default branch")

    remote_branch_name = match.group(1)
    branch_name = remote_branch_name.replace("refs/heads/", "")
    return branch_name


async def _get_pull_request_policy(project):
    # Pull request policy is special compared to most other things that exist
    # on a branch in that Taskcluster-Github only pays attention to what's on
    # the default branch. For that reason, we specifically look it up from
    # there rather than verifying the policy on all configured branches
    # for a project.
    config = yaml.safe_load(
        await tcyml.get(
            project.repo,
            repo_type=project.repo_type,
            ref=await _get_git_default_branch(project),
        )
    )
    return config.get("policy", {}).get("pullRequests")


@pytest.mark.asyncio
@with_aiohttp_session
async def check_pull_request_policies_for_git_repos():
    """Ensures that the pull-request policy defined in projects.yml
    matches the one in-repo.
    """
    skip = (
        "occ",  # tc.yml v0
        "firefox-profiler",  # not landed yet
        "fx-desktop-qa-automation",  # not landed yet
        "neqo",  # not landed yet
    )

    projects = [p for p in await Project.fetch_all() if not p.repo.endswith("*")]

    def filter_project(p):
        # TODO: find a better flag to filter out private repos
        return (
            p.repo_type == "git"
            and "private" not in p.repo
            and p.feature("github-pull-request")
            and p.alias not in skip
        )

    pr_policies = {
        project.alias: project.feature("github-pull-request", key="policy")
        for project in projects
        if filter_project(project)
    }
    github_pr_policies = {
        project.alias: await _get_pull_request_policy(project)
        for project in projects
        if filter_project(project)
    }
    assert pr_policies == github_pr_policies
