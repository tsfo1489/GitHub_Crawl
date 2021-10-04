# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from itemadapter import ItemAdapter
import sys, pymysql
from .items import *
from .configure import *

class SkkuGithubPipeline:
    def __init__(self) -> None:
        try :
            self.crawlDB = pymysql.connect(
                user=SQL_USER,
                passwd=SQL_PW,
                host=SQL_HOST,
                port=SQL_PORT,
                db=SQL_DB
            )
            self.cursor = self.crawlDB.cursor()
        except :
            print('ERROR: DB connection failed')
            sys.exit(1)
        self.wait = {}

    def process_item(self, item, spider):
        insert = False
        if type(item) == User:
            self.wait[item['github_id']] = item
        elif type(item) == UserUpdate:
            prev = self.wait[item['github_id']]
            if item['target'] == 'badge':
                prev['achievements'] = item['achievements']
                prev['highlights'] = item['highlights']
            elif item['target'] == 'activity':
                prev['total_commits'] += item['total_commits']
                prev['total_PRs'] += item['total_PRs']
                prev['total_issues'] += item['total_issues']
            elif item['target'] == 'repo_star':
                prev['stars'] += item['stars']
            prev['request_cnt'] -= 1
            self.wait[item['github_id']] = prev
            if prev['request_cnt'] == 0 :
                self.wait.pop(item['github_id'])
                insert = True
                data = prev
                print(prev)
        elif type(item) == Repo:
            self.wait[item['path']] = item
        elif type(item) == RepoUpdate:
            if item['target'] == 'main_page':
                self.wait[item['path']].update(item)
            elif item['target'] == 'pr':
                self.wait[item['path']].update(item)
                self.wait[item['path']]['request_cnt'] -= 1
            elif item['target'] == 'issue':
                self.wait[item['path']].update(item)
                self.wait[item['path']]['request_cnt'] -= 1
            elif item['target'] == 'commit':
                self.wait[item['path']]['code_edits'] += item['code_edits']
                self.wait[item['path']]['request_cnt'] -= 1
            if self.wait[item['path']]['request_cnt'] == 0:
                insert = True
                data = self.wait[item['path']]
                self.wait.pop(item['path'])
        elif type(item) == RepoContribute:
            insert = True
            data = item

        if insert:
            if type(data) == User:
                insert_sql = 'INSERT IGNORE INTO github_crawl.github_overview('
                insert_sql+= 'github_id, stars, followers, followings, total_repos, '
                insert_sql+= 'total_commits, total_PRs, total_issues, achievements, highlights) '
                insert_sql+= 'VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
                insert_data = (
                        data['github_id'], data['stars'], data['followers'], data['following'], 
                        data['total_repos'], data['total_commits'], data['total_PRs'], 
                        data['total_issues'], data['achievements'], data['highlights']
                    )
            if type(data) == Repo:
                print(data)
                insert_sql = 'INSERT IGNORE INTO github_repo_stats('
                insert_sql+= 'github_id, repo_name, stargazers_count, '
                insert_sql+= 'forks_count, commits_count, prs_count, '
                insert_sql+= 'open_issue_count, close_issue_count, '
                insert_sql+= 'wachers_count, dependencies, language, '
                insert_sql+= 'create_date, update_date, contributors_count, '
                insert_sql+= 'release_ver, release_count, license, readme, '
                insert_sql+= 'proj_short_desc) VALUES(%s, %s, %s, %s, %s, %s, '
                insert_sql+= '%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
                insert_data = (
                    data['github_id'], data['repo_name'], data['stargazers_count'],
                    data['forks_count'], data['commits_count'], data['prs_count'],
                    data['open_issue_count'], data['close_issue_count'], data['watchers'],
                    '', data['language'], data['create_date'], data['update_date'],
                    data['contributors'], data['release_ver'], data['release_count'],
                    data['license'], data['readme'], data['proj_short_desc']
                )
            if type(data) == RepoContribute:
                insert_sql = 'INSERT IGNORE INTO github_repo_contributor('
                insert_sql+= 'github_id, owner_id, repo_name) VALUES(%s, %s, %s)'
                insert_data = (data['github_id'], data['owner_id'], data['repo_name'])

            try:
                self.cursor.execute(insert_sql, insert_data)
                self.crawlDB.commit()
            except:
                print(insert_sql)
                print(insert_data)
                sys.exit(1)

        return item
