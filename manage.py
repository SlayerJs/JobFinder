"""Local review, application tracking, health and usage dashboard."""
import argparse
import json
import sqlite3
from src.database import JobDatabase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='jobs.db')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('dashboard')
    sub.add_parser('audit')
    listing = sub.add_parser('list')
    listing.add_argument('--status', default='REVIEW')
    track = sub.add_parser('track')
    track.add_argument('id')
    track.add_argument('--status', choices=['saved','applied','interview','rejected','offer'])
    track.add_argument('--notes')
    track.add_argument('--deadline')
    review = sub.add_parser('review')
    review.add_argument('id')
    review.add_argument('decision', choices=['APPROVED','REJECTED','PENDING'])
    review.add_argument('--tier', choices=['1','2','3','4'])
    review.add_argument('--reason', required=True)
    reeval = sub.add_parser('reevaluate')
    reeval.add_argument('--version', required=True, help='Requeue decisions not made with this criteria version')
    args = parser.parse_args()
    db = JobDatabase(args.db)
    try:
        if args.command == 'dashboard':
            queries = {
                'jobs': 'SELECT status,count(*) count FROM jobs GROUP BY status',
                'applications': 'SELECT application_status,count(*) count FROM jobs GROUP BY application_status',
                'sources': "SELECT source,count(*) total,sum(status='INVALID') invalid,sum(duplicate_of IS NOT NULL) duplicates FROM jobs GROUP BY source",
                'usage': 'SELECT model,sum(input_tokens) input_tokens,sum(output_tokens) output_tokens,sum(cache_hit_tokens) cache_hit_tokens,sum(estimated) estimated_requests,sum(cost_usd) estimated_cost_usd FROM api_usage GROUP BY model',
                'recent_scrapes': 'SELECT * FROM scraper_runs ORDER BY id DESC LIMIT 20',
                'notification_backlog': "SELECT count(*) count FROM jobs WHERE notification_status='PENDING'"}
            print(json.dumps({k:[dict(r) for r in db.conn.execute(q)] for k,q in queries.items()}, indent=2))
        elif args.command == 'list':
            print(json.dumps([dict(r) for r in db.conn.execute('SELECT id,title,company,url,ai_reason,application_status,notes,deadline FROM jobs WHERE status=?',(args.status,))], indent=2,ensure_ascii=False))
        elif args.command == 'audit':
            print(json.dumps(db.audit()))
        elif args.command in {'track','review'}:
            if not db.conn.execute('SELECT 1 FROM jobs WHERE id=?',(args.id,)).fetchone():
                parser.error('Unknown job ID')
            if args.command == 'review':
                if args.decision == 'APPROVED' and not args.tier:
                    parser.error('Approval requires --tier')
                db.update_job_status(args.id,args.decision,args.reason,args.tier or 'NONE','manual')
            else:
                if args.deadline:
                    from datetime import date
                    date.fromisoformat(args.deadline)
                with db.conn:
                    for field,value in [('application_status',args.status),('notes',args.notes),('deadline',args.deadline)]:
                        if value is not None:
                            db.conn.execute(f'UPDATE jobs SET {field}=? WHERE id=?',(value,args.id))
        elif args.command == 'reevaluate':
            with db.conn:
                cursor = db.conn.execute("UPDATE jobs SET status='PENDING',notification_status=CASE WHEN notification_status='SENT' THEN 'SENT' ELSE 'NONE' END WHERE status IN ('APPROVED','REJECTED','REVIEW') AND duplicate_of IS NULL AND coalesce(criteria_version,'') != ?",(args.version,))
            print(f'Requeued {cursor.rowcount} jobs')
    finally:
        db.close()


if __name__ == '__main__':
    main()
