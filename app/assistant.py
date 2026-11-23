from flask import Blueprint,render_template,request,session,current_app
from flask_login import current_user
from .routes import owner_required,fail
from .services.ask import answer,EXAMPLES
from .services.common import DomainError

assistant=Blueprint('assistant',__name__)


@assistant.route('/ask',methods=['GET','POST'])
@owner_required
def ask():
    result=None;question=''
    identity=f'{current_user.store_id}:{current_user.id}'
    saved=session.get('ask_context',{})
    context=saved.get('query') if saved.get('identity')==identity else None
    if request.method=='POST':
        if request.form.get('action')=='clear':
            session.pop('ask_context',None);context=None
        else:
            question=request.form.get('question','').strip()
            try:
                result=answer(current_user,question,context)
                # Store only the last query intent, not answers or store financial records.
                session['ask_context']={'identity':identity,'query':result['context']}
            except DomainError as exc: fail(exc)
    provider=current_app.config['ASK_PROVIDER']
    mode={'builtin':'Built-in interpreter','ollama':'Local AI','gemini':'Gemini'}.get(provider,'Built-in interpreter')
    return render_template('ask.html',result=result,question=question,examples=EXAMPLES,mode=mode,provider=provider)
