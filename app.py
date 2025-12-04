import os
from flask import Flask, render_template, redirect, url_for, request, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
import calendar as cal_module
import json
import statistics
import random
import math

app = Flask(__name__)

# --- ANTI-CACHE ---
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# --- CONFIG ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chiave-segreta-sviluppo-locale')
ADMIN_USER = "Matteo" 

database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///trading_journal.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELS ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), default='student') 
    trades = db.relationship('JournalEntry', backref='author', lazy=True)
    pros_settings = db.Column(db.Text, default="Trendline,Supporto,Rottura Struttura") 
    cons_settings = db.Column(db.Text, default="Contro Trend,News in arrivo")
    trading_rules = db.Column(db.Text, default="1. Attendi chiusura candela\n2. Non tradare durante news rosse")
    risk_rules = db.Column(db.Text, default="1. Max 1% rischio per trade\n2. Max 3 stop loss al giorno")
    custom_pairs = db.Column(db.Text, default="") 

class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    pair = db.Column(db.String(20), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    time = db.Column(db.String(10)) 
    direction = db.Column(db.String(10)) 
    risk_percent = db.Column(db.Float)
    rr_final = db.Column(db.Float)
    
    # Nuovi campi richiesti
    pips_tp = db.Column(db.Float, default=0)
    pips_sl = db.Column(db.Float, default=0)
    
    outcome = db.Column(db.String(20)) 
    result_percent = db.Column(db.Float) 
    
    # Timeframe logic split
    timeframe = db.Column(db.String(50)) # Barrier (Entry) M1-M30
    alignment = db.Column(db.String(50)) # Alignment (Trend) H1-M
    
    selected_pros = db.Column(db.Text) 
    selected_cons = db.Column(db.Text)
    setup = db.Column(db.String(50))
    sentiment = db.Column(db.String(50))
    screen_pre = db.Column(db.Text) 
    screen_post = db.Column(db.String(200)) 
    notes = db.Column(db.Text)
    emotions = db.Column(db.String(50))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- ROUTES ---
@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Utente già esistente.', 'danger')
            return redirect(url_for('register'))
        role = 'admin' if username == ADMIN_USER else 'student'
        new_user = User(username=username, password=bcrypt.generate_password_hash(password).decode('utf-8'), role=role)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and bcrypt.check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Login fallito.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        current_user.pros_settings = ",".join([p.strip() for p in request.form.getlist('pros_item') if p.strip()])
        current_user.cons_settings = ",".join([c.strip() for c in request.form.getlist('cons_item') if c.strip()])
        current_user.trading_rules = request.form.get('trading_rules')
        current_user.risk_rules = request.form.get('risk_rules')
        current_user.custom_pairs = request.form.get('custom_pairs')
        db.session.commit()
        flash('Setup aggiornato!', 'success')
        return redirect(url_for('settings'))
    
    u_pros = current_user.pros_settings.split(',') if current_user.pros_settings else []
    u_cons = current_user.cons_settings.split(',') if current_user.cons_settings else []
    while len(u_pros) < 7: u_pros.append("")
    while len(u_cons) < 7: u_cons.append("")
    return render_template('settings.html', user_pros=u_pros, user_cons=u_cons, user=current_user)

@app.route('/rules', methods=['GET', 'POST'])
@login_required
def rules():
    if request.method == 'POST':
        current_user.trading_rules = request.form.get('trading_rules')
        current_user.risk_rules = request.form.get('risk_rules')
        db.session.commit()
        flash('Regole aggiornate!', 'success')
        return redirect(url_for('rules'))
    return render_template('rules.html', user=current_user)

@app.route('/admin_panel', methods=['GET', 'POST'])
@login_required
def admin_panel():
    if current_user.role != 'admin':
        abort(403)
        
    if request.method == 'POST':
        target_username = request.form.get('target_username')
        action = request.form.get('action')
        
        user_to_mod = User.query.filter_by(username=target_username).first()
        
        if not user_to_mod:
            flash(f'Utente "{target_username}" non trovato.', 'danger')
        elif user_to_mod.username == ADMIN_USER:
             flash('Impossibile modificare il Super Admin.', 'danger')
        else:
            if action == 'promote':
                user_to_mod.role = 'admin'
                flash(f'{target_username} è ora ADMIN.', 'success')
            elif action == 'demote':
                user_to_mod.role = 'student'
                flash(f'{target_username} è ora studente.', 'warning')
            db.session.commit()
            
    users = User.query.all()
    return render_template('admin_users.html', users=users, super_admin=ADMIN_USER, user=current_user)

@app.route('/dashboard')
@login_required
def dashboard():
    pair_filter = request.args.get('pair_filter')
    outcome_filter = request.args.get('outcome_filter')
    date_filter = request.args.get('date_filter')

    query = JournalEntry.query
    if current_user.role != 'admin':
        query = query.filter_by(user_id=current_user.id)
    
    if pair_filter: query = query.filter(JournalEntry.pair == pair_filter)
    if outcome_filter: query = query.filter(JournalEntry.outcome == outcome_filter)
    if date_filter:
        year, month = date_filter.split('-')
        query = query.filter(db.extract('year', JournalEntry.date) == int(year))
        query = query.filter(db.extract('month', JournalEntry.date) == int(month))

    filtered_trades = query.all()
    filter_stats = {'total': len(filtered_trades), 'net_profit': 0, 'win_rate': 0, 'avg_rr': 0}
    
    if filtered_trades:
        active = [t for t in filtered_trades if t.outcome in ['Target', 'Stop Loss', 'Breakeven']]
        wins = [t for t in active if t.outcome == 'Target']
        filter_stats['net_profit'] = round(sum((t.result_percent or 0) for t in filtered_trades), 2)
        if len(active) > 0: filter_stats['win_rate'] = round((len(wins) / len(active)) * 100, 1)
        rrs = [t.rr_final for t in filtered_trades if t.rr_final is not None and t.rr_final > 0]
        if rrs: filter_stats['avg_rr'] = round(sum(rrs) / len(rrs), 2)

    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(JournalEntry.date.desc()).paginate(page=page, per_page=15, error_out=False)
    
    u_pros = [p for p in (current_user.pros_settings.split(',') if current_user.pros_settings else []) if p]
    u_cons = [c for c in (current_user.cons_settings.split(',') if current_user.cons_settings else []) if c]
    custom_pairs_list = [p.strip().upper() for p in (current_user.custom_pairs.split(',') if current_user.custom_pairs else []) if p.strip()]

    return render_template('dashboard.html', pagination=pagination, admin_view=(current_user.role == 'admin'), 
                           user=current_user, user_pros=u_pros, user_cons=u_cons, 
                           filter_stats=filter_stats, custom_pairs=custom_pairs_list)

@app.route('/statistics')
@login_required
def statistics_page():
    admin_view = (current_user.role == 'admin')
    base_query = JournalEntry.query
    if not admin_view:
        base_query = base_query.filter_by(user_id=current_user.id)
    
    # Filtro opzionale mese per il calendario
    selected_month_str = request.args.get('month_ref', datetime.now().strftime('%Y-%m'))
    sel_year, sel_month = map(int, selected_month_str.split('-'))

    trades = base_query.order_by(JournalEntry.date.asc()).all()
    
    unique_dates = set(t.date for t in trades)
    total_days = len(unique_dates)

    if not trades: 
        return render_template('statistics.html', no_data=True, user=current_user, admin_view=admin_view, total_trades=0, total_days=0)

    # --- BASE KPI ---
    active_trades = [t for t in trades if t.outcome in ['Target', 'Stop Loss', 'Breakeven']]
    wins = [(t.result_percent or 0) for t in active_trades if t.outcome == 'Target']
    losses = [(t.result_percent or 0) for t in active_trades if t.outcome == 'Stop Loss']
    
    total_active = len(active_trades)
    num_wins = len(wins)
    num_losses = len(losses)
    
    win_rate = round((num_wins / total_active * 100), 2) if total_active > 0 else 0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_result = round(gross_profit - gross_loss, 2)
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else round(gross_profit, 2)
    
    unique_weeks = len(set(t.date.strftime('%Y-%W') for t in trades))
    avg_weekly_trades = round(len(trades) / unique_weeks, 1) if unique_weeks > 0 else len(trades)

    returns = [(t.result_percent or 0) for t in active_trades]
    std_dev = statistics.stdev(returns) if len(returns) > 1 else 0
    avg_return = statistics.mean(returns) if returns else 0
    sharpe_ratio = round(avg_return / std_dev, 2) if std_dev > 0 else 0
    
    avg_win = round(statistics.mean(wins), 2) if wins else 0
    avg_loss = round(statistics.mean(losses), 2) if losses else 0
    
    # --- RISK OF RUIN (Fixato) ---
    risk_of_ruin = {'10': 0, '20': 0, '100': 0}
    
    if total_active > 5:
        if gross_loss == 0:
            risk_of_ruin = {'10': 0, '20': 0, '100': 0}
        else:
            win_prob = win_rate / 100
            loss_prob = 1 - win_prob
            
            mc_drawdowns = []
            for _ in range(1000): # Aumentato numero simulazioni
                sim_equity = 0
                max_dd = 0
                peak = 0
                for _ in range(100):
                    outcome = random.choices([avg_win, avg_loss], weights=[win_prob, loss_prob])[0]
                    sim_equity += outcome
                    peak = max(peak, sim_equity)
                    dd = peak - sim_equity
                    max_dd = max(max_dd, dd)
                mc_drawdowns.append(max_dd)
            
            risk_of_ruin['10'] = round(len([d for d in mc_drawdowns if d >= 10]) / 1000 * 100, 1)
            risk_of_ruin['20'] = round(len([d for d in mc_drawdowns if d >= 20]) / 1000 * 100, 1)
            risk_of_ruin['100'] = round(len([d for d in mc_drawdowns if d >= 100]) / 1000 * 100, 1)

    # --- CALENDAR TOPSTEP STYLE ---
    month_trades = [t for t in trades if t.date.year == sel_year and t.date.month == sel_month]
    month_pl = sum([(t.result_percent or 0) for t in month_trades])
    
    cal_obj = cal_module.Calendar(firstweekday=6) 
    month_days = cal_obj.monthdayscalendar(sel_year, sel_month)
    
    calendar_data = []
    for week in month_days:
        week_stats = {'days': [], 'week_pl': 0, 'trade_count': 0}
        for day in week:
            if day == 0:
                week_stats['days'].append(None)
            else:
                d_trades = [t for t in month_trades if t.date.day == day]
                d_pl = round(sum([(t.result_percent or 0) for t in d_trades]), 2)
                d_count = len(d_trades)
                week_stats['days'].append({'day': day, 'pl': d_pl, 'count': d_count})
                week_stats['week_pl'] += d_pl
                week_stats['trade_count'] += d_count
        week_stats['week_pl'] = round(week_stats['week_pl'], 2)
        calendar_data.append(week_stats)

    # --- TOP WEEKS ANALYSIS ---
    week_performance = {1: {'wins':0, 'total':0, 'pl':0}, 2: {'wins':0, 'total':0, 'pl':0}, 
                        3: {'wins':0, 'total':0, 'pl':0}, 4: {'wins':0, 'total':0, 'pl':0}, 5: {'wins':0, 'total':0, 'pl':0}}
    for t in trades:
        w_num = (t.date.day - 1) // 7 + 1
        if w_num > 5: w_num = 5
        week_performance[w_num]['total'] += 1
        week_performance[w_num]['pl'] += (t.result_percent or 0)
        if t.outcome == 'Target': week_performance[w_num]['wins'] += 1
    week_table = []
    for w, data in week_performance.items():
        if data['total'] > 0:
            wr = round(data['wins']/data['total']*100, 1)
            week_table.append({'name': f"Settimana {w}", 'win_rate': wr, 'pl': round(data['pl'], 2), 'total': data['total']})
    week_table.sort(key=lambda x: x['pl'], reverse=True)
    best_week = week_table[0]['name'] if week_table else "N/D"

    # --- HELPER PER TABELLE ---
    def make_stats_table(stats_dict):
        table = []
        for key, data in stats_dict.items():
            wr = round(data['wins']/data['total']*100, 1) if data['total'] > 0 else 0
            table.append({'name': key, 'total': data['total'], 'win_rate': wr, 'result': round(data['pl'], 2)})
        table.sort(key=lambda x: x['result'], reverse=True)
        return table

    # --- TIMEFRAMES ---
    tf_stats = {}
    for t in active_trades:
        if t.timeframe:
            for tf in t.timeframe.split(','):
                tf = tf.strip()
                if tf not in tf_stats: tf_stats[tf] = {'total': 0, 'wins': 0, 'pl': 0}
                tf_stats[tf]['total'] += 1
                tf_stats[tf]['pl'] += (t.result_percent or 0)
                if t.outcome == 'Target': tf_stats[tf]['wins'] += 1
    tf_table = make_stats_table(tf_stats)

    # --- ALIGNMENT ---
    align_stats = {}
    for t in active_trades:
        if t.alignment:
            for al in t.alignment.split(','):
                al = al.strip()
                if al not in align_stats: align_stats[al] = {'total': 0, 'wins': 0, 'pl': 0}
                align_stats[al]['total'] += 1
                align_stats[al]['pl'] += (t.result_percent or 0)
                if t.outcome == 'Target': align_stats[al]['wins'] += 1
    align_table = make_stats_table(align_stats)

    # --- CONFLUENZE (PROS) ANALYSIS ---
    pros_stats = {}
    for t in active_trades:
        if t.selected_pros:
            for p in t.selected_pros.split(','):
                p = p.strip()
                if not p: continue
                if p not in pros_stats: pros_stats[p] = {'total': 0, 'wins': 0, 'pl': 0}
                pros_stats[p]['total'] += 1
                pros_stats[p]['pl'] += (t.result_percent or 0)
                if t.outcome == 'Target': pros_stats[p]['wins'] += 1
    pros_table = make_stats_table(pros_stats)

    # --- RISCHI (CONS) ANALYSIS - NUOVO ---
    cons_stats = {}
    for t in active_trades:
        if t.selected_cons:
            for c in t.selected_cons.split(','):
                c = c.strip()
                if not c: continue
                if c not in cons_stats: cons_stats[c] = {'total': 0, 'wins': 0, 'pl': 0}
                cons_stats[c]['total'] += 1
                cons_stats[c]['pl'] += (t.result_percent or 0)
                if t.outcome == 'Target': cons_stats[c]['wins'] += 1
    cons_table = make_stats_table(cons_stats)

    # --- TOP DAYS ---
    day_map = {0: 'Lun', 1: 'Mar', 2: 'Mer', 3: 'Gio', 4: 'Ven', 5: 'Sab', 6: 'Dom'}
    day_stats = {d: {'wins': 0, 'total': 0, 'res': 0} for d in day_map.values()}
    for t in trades:
        d = day_map[t.date.weekday()]
        day_stats[d]['total'] += 1
        day_stats[d]['res'] += (t.result_percent or 0)
        if t.outcome == 'Target': day_stats[d]['wins'] += 1
    day_table = []
    for d, data in day_stats.items():
        if data['total'] > 0:
            wr = round(data['wins']/data['total']*100, 1)
            day_table.append({'name': d, 'total': data['total'], 'win_rate': wr, 'res': round(data['res'], 2)})
    day_table.sort(key=lambda x: x['res'], reverse=True)

    # --- CHART & MONTE CARLO ---
    mc_simulations = []
    real_returns = [(t.result_percent or 0) for t in active_trades]
    if len(real_returns) > 5:
        for _ in range(20):
            sim_curve = []
            cum_pl = 0
            shuffled = random.choices(real_returns, k=len(real_returns)) 
            for r in shuffled:
                cum_pl += r
                sim_curve.append(round(cum_pl, 2))
            mc_simulations.append(sim_curve)
    
    chart_labels, chart_data = [], []
    run_tot = 0
    chronological = sorted(trades, key=lambda x: x.date)
    for t in chronological:
        if t.outcome in ['Target', 'Stop Loss', 'Breakeven'] and t.result_percent is not None:
            run_tot += t.result_percent
            chart_labels.append(t.date.strftime('%d/%m'))
            chart_data.append(round(run_tot, 2))
    
    projection_data = []
    if total_active > 0:
        expectancy = (avg_win * (win_rate/100)) - (abs(avg_loss) * ((100-win_rate)/100))
        last_equity = chart_data[-1] if chart_data else 0
        projection_data = [last_equity] 
        for i in range(1, 21):
            projection_data.append(round(last_equity + (expectancy * i), 2))

    return render_template('statistics.html', no_data=False, user=current_user, admin_view=admin_view,
                           win_rate=win_rate, profit_factor=profit_factor, net_result=net_result, 
                           avg_weekly_trades=avg_weekly_trades, sharpe_ratio=sharpe_ratio, risk_of_ruin=risk_of_ruin,
                           total_active=total_active, total_trades=len(trades), num_wins=num_wins, num_losses=num_losses,
                           tf_table=tf_table, align_table=align_table, day_table=day_table, week_table=week_table,
                           pros_table=pros_table, cons_table=cons_table,
                           chart_labels=json.dumps(chart_labels), chart_data=json.dumps(chart_data),
                           mc_simulations=json.dumps(mc_simulations), projection_data=json.dumps(projection_data),
                           calendar_data=calendar_data, month_pl=month_pl,
                           selected_month=selected_month_str, best_week=best_week, 
                           total_days=total_days)

@app.route('/add_trade', methods=['POST'])
@login_required
def add_trade():
    try:
        sc = ",".join([l for l in [request.form.get('link1','').strip(), request.form.get('link2','').strip()] if l])
        
        barriers = ",".join(request.form.getlist('timeframe_barrier'))
        aligns = ",".join(request.form.getlist('timeframe_align'))

        new_entry = JournalEntry(
            user_id=current_user.id, 
            pair=request.form.get('pair'), 
            date=datetime.strptime(request.form.get('date'), '%Y-%m-%d'),
            time=request.form.get('time'), 
            direction=request.form.get('direction'),
            risk_percent=float(request.form.get('risk_percent') or 0), 
            rr_final=float(request.form.get('rr_final') or 0),
            pips_sl=float(request.form.get('pips_sl') or 0),
            pips_tp=float(request.form.get('pips_tp') or 0),
            outcome=request.form.get('outcome'), 
            result_percent=float(request.form.get('result_percent') or 0),
            timeframe=barriers, 
            alignment=aligns,   
            selected_pros=",".join(request.form.getlist('pros')),
            selected_cons=",".join(request.form.getlist('cons')), 
            screen_pre=sc, 
            emotions=request.form.get('emotions'), 
            notes=request.form.get('notes')
        )
        db.session.add(new_entry)
        db.session.commit()
        flash('Trade aggiunto!', 'success')
    except Exception as e: flash(f'Errore: {str(e)}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/delete_trade/<int:id>')
@login_required
def delete_trade(id):
    trade = JournalEntry.query.get_or_404(id)
    if trade.user_id == current_user.id or current_user.role == 'admin':
        db.session.delete(trade)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/edit_trade/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_trade(id):
    trade = JournalEntry.query.get_or_404(id)
    if trade.user_id != current_user.id and current_user.role != 'admin': return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        trade.pair = request.form.get('pair')
        trade.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d')
        trade.time = request.form.get('time')
        trade.direction = request.form.get('direction')
        trade.outcome = request.form.get('outcome')
        trade.risk_percent = float(request.form.get('risk_percent') or 0)
        trade.result_percent = float(request.form.get('result_percent') or 0)
        trade.rr_final = float(request.form.get('rr_final') or 0)
        trade.pips_sl = float(request.form.get('pips_sl') or 0)
        trade.pips_tp = float(request.form.get('pips_tp') or 0)
        trade.emotions = request.form.get('emotions')
        trade.notes = request.form.get('notes')
        
        trade.timeframe = ",".join(request.form.getlist('timeframe_barrier'))
        trade.alignment = ",".join(request.form.getlist('timeframe_align'))
        
        trade.selected_pros = ",".join(request.form.getlist('pros'))
        trade.selected_cons = ",".join(request.form.getlist('cons'))
        trade.screen_pre = ",".join([l for l in [request.form.get('link1','').strip(), request.form.get('link2','').strip()] if l])
        db.session.commit()
        flash('Modificato!', 'success')
        return redirect(url_for('dashboard'))
    
    curr_barriers = trade.timeframe.split(',') if trade.timeframe else []
    curr_aligns = trade.alignment.split(',') if trade.alignment else []
    
    curr_pros = trade.selected_pros.split(',') if trade.selected_pros else []
    curr_cons = trade.selected_cons.split(',') if trade.selected_cons else []
    cur_lnks = trade.screen_pre.split(',') if trade.screen_pre else []
    u_pros = [p for p in (current_user.pros_settings.split(',') if current_user.pros_settings else []) if p]
    u_cons = [c for c in (current_user.cons_settings.split(',') if current_user.cons_settings else []) if c]
    custom_pairs_list = [p.strip().upper() for p in (current_user.custom_pairs.split(',') if current_user.custom_pairs else []) if p.strip()]

    return render_template('edit_trade.html', trade=trade, 
                           curr_barriers=curr_barriers, curr_aligns=curr_aligns,
                           curr_pros=curr_pros, curr_cons=curr_cons, 
                           user_pros_list=u_pros, user_cons_list=u_cons, custom_pairs=custom_pairs_list,
                           val_link1=cur_lnks[0] if len(cur_lnks)>0 else '', val_link2=cur_lnks[1] if len(cur_lnks)>1 else '')

with app.app_context(): db.create_all()
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)