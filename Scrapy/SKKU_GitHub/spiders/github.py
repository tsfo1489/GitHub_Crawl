from bs4 import BeautifulSoup
import scrapy, json, math
from datetime import datetime, timedelta
from ..items import *
from ..configure import *


API_URL = 'https://api.github.com'
HTML_URL = 'https://github.com'
class GithubSpider(scrapy.Spider):
    name = 'github'

    def __init__(self, ids='', **kwargs):
        self.ids = open('student_list.txt', 'r').read().split()
        print(self.ids)
        if ids != '' :
            self.ids = ids.split(',')

    def start_requests(self):
        for id in self.ids :
            yield self.api_get(f'users/{id}', self.parse_user)
    
    def __end_of_month(self, now: datetime) :
        next_month = now.month % 12 + 1
        next_year = now.year + now.month // 12
        return datetime(next_year, next_month, 1) - timedelta(seconds=1)

    def api_get(self, endpoint, callback, metadata={}, page=1, per_page=100) :
        req = scrapy.Request(
                f'{API_URL}/{endpoint}?page={page}&per_page={per_page}',
                callback,
                meta=metadata,
                dont_filter=True
                )
        
        return req

    def parse_user(self, res) :
        user_json = json.loads(res.body)
        github_id = user_json['login']
        user_item = User()
        user_item['github_id'] = github_id
        user_item['followers'] = user_json['followers']
        user_item['followings'] = user_json['following']
        user_item['total_repos'] = user_json['public_repos']
        user_item['total_commits'] = 0
        user_item['total_PRs'] = 0
        user_item['total_issues'] = 0
        user_item['stars'] = 0
        user_item['request_cnt'] = 1 + math.ceil(user_json['public_repos'] / 100)

        created_date = user_json['created_at'][:7]
        updated_date = user_json['updated_at'][:7]
        pivot_date = datetime.strptime(created_date, '%Y-%m')
        end_date = datetime.strptime(updated_date, '%Y-%m')
        end_date = self.__end_of_month(end_date)
        while pivot_date < end_date :
            pivot_date = self.__end_of_month(pivot_date) + timedelta(days=1)
            user_item['request_cnt'] += 1
        yield user_item


        yield self.api_get(
            f'users/{github_id}/repos', 
            self.parse_user_repo,
            {'github_id': github_id, 'page': 1}
            )

        pivot_date = datetime.strptime(created_date, '%Y-%m')
        while pivot_date < end_date :
            from_date = pivot_date.strftime('%Y-%m-%d')
            to_date = self.__end_of_month(pivot_date).strftime('%Y-%m-%d')
            yield scrapy.Request(
                f'{HTML_URL}/{github_id}/?tab=overview&from={from_date}&to={to_date}',
                self.parse_user_update,
                meta={'github_id':github_id, 'from': from_date, 'to': to_date},
            )
            pivot_date = self.__end_of_month(pivot_date) + timedelta(days=1)
        
        yield scrapy.Request(
            f'{HTML_URL}/{user_json["login"]}', 
            self.parse_user_page,
            meta={'github_id':github_id}
        )

    def parse_user_update(self, res):
        github_id = res.meta['github_id']
        soup = BeautifulSoup(res.body, 'html.parser')
        user_update = UserUpdate()
        user_update['github_id'] = github_id
        user_update['target'] = 'activity'
        user_update['total_commits'] = 0
        user_update['total_PRs'] = 0
        user_update['total_issues'] = 0
        
        user_period = UserPeriod()
        user_period['github_id'] = github_id
        user_period['start_yymm'] = res.meta['from']
        user_period['end_yymm'] = res.meta['to']
        user_period['num_of_cr_repos'] = 0
        user_period['stars'] = 0
        owned_repo = set()
        contributed_repo = set()

        for event in soup.select('.TimelineItem-body'):
            summary = event.select_one('summary')
            body = event.select('details > div > details')
            if summary == None :
                summary = event.select_one('h4')
                if summary == None:
                    pass
                else:
                    summary = ' '.join(summary.text.strip().split())
                    if 'Opened their first issue' in summary :
                        user_update['total_issues'] += 1
                    if 'Opened their first pull request' in summary :
                        user_update['total_PRs'] += 1
                    if 'Created an issue' in summary :
                        user_update['total_issues'] += 1
                    if 'Created a pull request' in summary :
                        user_update['total_PRs'] += 1
                continue
            summary = summary.text.strip().split()
            if summary[0] == 'Created':
                # Create Commit
                if summary[2] == 'commit' or summary[2] == 'commits':
                    commit_list = event.select('li')
                    for commit in commit_list :
                        detail = commit.select('a')
                        commit_cnt = int(detail[1].text.strip().split()[0])
                        user_update['total_commits']  += commit_cnt
                        repo = detail[0].text
                        if repo.split('/')[0] != github_id :
                            contributed_repo.add(repo)
                        else :
                            owned_repo.add(repo)
                # Create Repository
                elif summary[2] == 'repository' or summary[2] == 'repositories':
                    user_period['num_of_cr_repos'] += 1
            elif summary[0] == 'Opened' :
                # Open Issues
                if 'issue' in summary or 'issues' in summary :
                    issue_list = event.select('li')
                    user_update['total_issues'] += len(issue_list)
                    for issue_repo in body:
                        repo = issue_repo.select_one('summary span').text.strip()
                        repo = repo.split('/')
                        if repo[0] != github_id :
                            contributed_repo.add('/'.join(repo))
                        else :
                            owned_repo.add('/'.join(repo))
                        for issue_tag in issue_repo.select('li'):
                            issue = Issue()
                            issue['github_id'] = github_id
                            issue['owner_id'] = repo[0]
                            issue['repo_name'] = repo[1]
                            issue['title'] = issue_tag.select_one('a > span').text
                            issue['number'] = issue_tag.select_one('a')['href']
                            issue['number'] = issue['number'][issue['number'].rfind('/') + 1:]
                            date = issue_tag.select_one('time').text.strip()
                            date = datetime.strptime(date, '%b %d')
                            issue['date'] = date.replace(year=int(res.meta['from'][:4]))
                            yield issue
                # Open Pull Requests
                elif 'request' in summary or 'requests' in summary :
                    pr_list = event.select('li')
                    user_update['total_PRs'] += len(pr_list)
                    for pr_repo in body:
                        repo = pr_repo.select_one('summary span').text.strip()
                        repo = repo.split('/')
                        if repo[0] != github_id :
                            contributed_repo.add('/'.join(repo))
                        else :
                            owned_repo.add('/'.join(repo))
                        for pr_tag in pr_repo.select('li'):
                            pr = PullRequest()
                            pr['github_id'] = github_id
                            pr['owner_id'] = repo[0]
                            pr['repo_name'] = repo[1]
                            pr['title'] = pr_tag.select_one('a > span').text
                            pr['number'] = pr_tag.select_one('a')['href']
                            pr['number'] = pr['number'][pr['number'].rfind('/') + 1:]
                            date = pr_tag.select_one('time').text.strip()
                            date = datetime.strptime(date, '%b %d')
                            pr['date'] = date.replace(year=int(res.meta['from'][:4]))
                            yield pr
        yield user_update

        user_period['num_of_co_repos'] = len(contributed_repo)
        user_period['num_of_commits'] = user_update['total_commits']
        user_period['num_of_PRs'] = user_update['total_PRs']
        user_period['num_of_issues'] = user_update['total_issues']
        yield user_period

        for repo in owned_repo :
            contribute = RepoContribute()
            contribute['github_id'] = github_id
            contribute['owner_id'], contribute['repo_name'] = repo.split('/')
            yield contribute
            yield self.api_get(f'repos/{repo}', self.parse_repo, metadata={'from': github_id})
        for repo in contributed_repo :
            contribute = RepoContribute()
            contribute['github_id'] = github_id
            contribute['owner_id'], contribute['repo_name'] = repo.split('/')
            yield contribute
            yield self.api_get(f'repos/{repo}', self.parse_repo, metadata={'from': github_id})

    def parse_user_page(self, res):
        soup = BeautifulSoup(res.body, 'html.parser')
        info_list = [tag.parent for tag in soup.select('h2.h4.mb-2')]
        user_data = UserUpdate()
        user_data['github_id'] = res.meta['github_id']
        user_data['target'] = 'badge'
        user_data['achievements'] = None
        user_data['highlights'] = None
        for info in info_list :
            if info.h2.text == 'Achievements' :
                user_data['achievements'] = ', '.join(
                    [tag['alt'] for tag in info.select('img')]
                    )
            if info.h2.text == 'Highlights' :
                user_data['highlights'] = ', '.join(
                    [tag.text.strip() for tag in info.select('li')]
                )
        yield user_data
    
    def parse_user_repo(self, res):
        json_data = json.loads(res.body)
        user_data = UserUpdate()
        github_id = res.meta['github_id']
        user_data['github_id'] = github_id
        user_data['target'] = 'repo_star'
        user_data['stars'] = 0
        for repo_data in json_data:
            user_data['stars'] += repo_data['stargazers_count']
        yield user_data
        
        if len(json_data) == 100 :
            metadata = res.meta
            metadata['page'] += 1
            yield self.api_get(
                f'users/{github_id}/repos',
                self.parse_user_repo,
                metadata,
                page = metadata['page']
                )

    def parse_repo(self, res):
        json_data = json.loads(res.body)
        repo_data = Repo()
        github_id = json_data['owner']['login']
        repo_name = json_data['name']
        repo_data['github_id'] = github_id
        repo_data['repo_name'] = repo_name
        repo_data['path'] = f'{github_id}/{repo_name}'
        repo_data['stargazers_count'] = json_data['stargazers_count']
        repo_data['forks_count'] = json_data['forks_count']
        repo_data['watchers_count'] = None if not 'subscribers_count' in json_data else json_data['subscribers_count']
        repo_data['create_date'] = datetime.fromisoformat(json_data['created_at'][:-1])
        repo_data['update_date'] = datetime.fromisoformat(json_data['updated_at'][:-1])
        repo_data['language'] = json_data['language']
        repo_data['proj_short_desc'] = json_data['description']
        repo_data['license'] = None if json_data['license'] is None else json_data['license']['name']
        yield repo_data

        yield scrapy.Request(
            f'{HTML_URL}/{github_id}/{repo_name}',
            self.parse_repo_page,
            meta={'github_id': github_id, 'repo_name': repo_name, 'from': res.meta['from']},
            dont_filter=True
        )

    def parse_repo_page(self, res):
        soup = BeautifulSoup(res.body, 'html.parser')
        github_id = res.meta['github_id']
        repo_name = res.meta['repo_name']
        repo_data = RepoUpdate()
        repo_data['path'] = f'{github_id}/{repo_name}'
        repo_data['target'] = 'main_page'
        release_tag = soup.select_one(f'a[href="/{github_id}/{repo_name}/releases"]')
        if release_tag is None :
            repo_data['release_ver'] = None
            repo_data['release_count'] = 0
        else:
            release_tag = release_tag.parent.parent
            if release_tag.select_one('span.Counter') is None:
                repo_data['release_ver'] = None
                repo_data['release_count'] = 0
            else :
                repo_data['release_count'] = int(release_tag.select_one('span.Counter').text)
                repo_data['release_ver'] = release_tag.select_one('a > div span').text[:45]

        contributor_tag = soup.select_one(f'a[href="/{github_id}/{repo_name}/graphs/contributors"]')
        if not contributor_tag is None:
            contributor_tag = contributor_tag.parent.parent
            repo_data['contributors_count'] = int(contributor_tag.select_one('span.Counter').text.replace(',',''))
        else:
            repo_data['contributors_count'] = 1
        
        repo_data['readme'] = not soup.select_one('div#readme') is None
        repo_data['commits_count'] = int(soup.select_one('div.Box-header strong').text.replace(',',''))
        repo_data['request_cnt'] = 3
        yield repo_data

        yield scrapy.Request(
            f'{HTML_URL}/{repo_data["path"]}/pulls',
            self.parse_repo_pr,
            meta={'path': repo_data['path']}
        )
        yield scrapy.Request(
            f'{HTML_URL}/{repo_data["path"]}/issues',
            self.parse_repo_issue,
            meta={'path': repo_data['path']}
        )
        yield self.api_get(
            f'repos/{github_id}/{repo_name}/commits',
            self.parse_repo_commit, {'path': repo_data['path'], 'page': 1, 'from': res.meta['from']}
        )
        
        yield scrapy.Request(
            f'{HTML_URL}/{repo_data["path"]}/network/dependencies',
            self.parse_repo_dependencies,
            meta={'path': repo_data['path']}
        )
    
    def parse_repo_pr(self, res):
        soup = BeautifulSoup(res.body, 'html.parser')
        repo_data = RepoUpdate()
        repo_data['path'] = res.meta['path']
        repo_data['target'] = 'pr'
        prs_cnt = soup.select_one('a[data-ga-click="Pull Requests, Table state, Open"]').parent
        prs_cnt = [x.text.strip().replace(',','').split() for x in prs_cnt.select('a')]
        repo_data['prs_count'] = int(prs_cnt[0][0]) + int(prs_cnt[1][0])
        yield repo_data

    def parse_repo_issue(self, res):
        soup = BeautifulSoup(res.body, 'html.parser')
        repo_data = RepoUpdate()
        repo_data['path'] = res.meta['path']
        repo_data['target'] = 'issue'
        issue_cnt = soup.select_one('a[data-ga-click="Issues, Table state, Open"]').parent
        issue_cnt = [x.text.strip().replace(',','').split() for x in issue_cnt.select('a')]
        repo_data['open_issue_count'] = int(issue_cnt[0][0])
        repo_data['close_issue_count'] = int(issue_cnt[1][0])
        yield repo_data
    
    def parse_repo_commit(self, res):
        json_data = json.loads(res.body)
        path = res.meta['path']
        for commits in json_data:
            committer = commits['committer']
            if committer is not None and 'login' in committer :
                committer = committer['login']
            author = commits['author']
            if author is not None and 'login' in author :
                author = author['login']
            if author == res.meta['from'] or author == res.meta['from']:
                yield self.api_get(
                    f'repos/{path}/commits/{commits["sha"]}',
                    self.parse_repo_commit_edits,
                    {'path': res.meta['path']}
                )
        
        if len(json_data) == 100 :
            metadata = res.meta
            metadata['page'] += 1
            yield self.api_get(
                f'repos/{path}/commits',
                self.parse_repo_commit,
                metadata,
                page = metadata['page']
                )

    def parse_repo_commit_edits(self, res):
        json_data = json.loads(res.body)
        commit_data = RepoCommit()
        commit_data['github_id'] = res.meta['path'].split('/')[0]
        commit_data['repo_name'] = res.meta['path'].split('/')[1]
        commit_data['sha'] = json_data['sha']
        committer = json_data['committer']
        if committer is None or 'login' not in committer:
            commit_data['committer_github'] = None
        else:
            commit_data['committer_github'] = committer['login']
        commit_data['committer_date'] = datetime.fromisoformat(json_data['commit']['committer']['date'][:-1])
        commit_data['committer'] = json_data['commit']['committer']['email']
        author = json_data['author']
        if author is None or 'login' not in author:
            commit_data['author_github'] = None
        else:
            commit_data['author_github'] = author['login']
        commit_data['author_date'] = datetime.fromisoformat(json_data['commit']['author']['date'][:-1])
        commit_data['author'] = json_data['commit']['author']['email']
        commit_data['additions'] = json_data['stats']['additions']
        commit_data['deletions'] = json_data['stats']['deletions']
        yield commit_data
    
    def parse_repo_dependencies(self, res):
        soup = BeautifulSoup(res.body, 'html.parser')
        repo_data = RepoUpdate()
        repo_data['path'] = res.meta['path']
        repo_data['target'] = 'dependencies'
        repo_data['dependencies'] = 0
        for tag in soup.select('.Box .Counter'):
            repo_data['dependencies'] = max(repo_data['dependencies'], int(tag.text.replace(',', '')))
        yield repo_data