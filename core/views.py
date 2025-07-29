from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import transaction
import json
import requests
import random
from django.conf import settings

from .models import Profile, Quest, Habit, LogEntry, AIResponse, StatusEffect
from .utils import generate_ai_response, parse_ai_action, generate_daily_quests, clean_ai_response, get_enhanced_personality_prompt


def welcome(request):
    """Welcome/Landing page with anime intro"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'welcome.html')


def register(request):
    """Character creation/registration page"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        name = request.POST.get('name')
        role = request.POST.get('role', 'student')
        interests = request.POST.getlist('interests')
        goal = request.POST.get('goal', '')
        
        # Validate input
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists')
            return render(request, 'register.html')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists')
            return render(request, 'register.html')
        
        try:
            with transaction.atomic():
                # Create user
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=name
                )
                
                # Use instant fallback character data for fast registration
                # AI will enhance this in the background
                character_classes = [
                    "Novice Scholar", "Aspiring Warrior", "Rising Explorer",
                    "Eager Student", "Determined Seeker", "Brave Adventurer"
                ]
                
                default_stats = {
                    "strength": 12,
                    "intelligence": 13, 
                    "charisma": 11,
                    "endurance": 12,
                    "luck": 12
                }
                
                # Create profile with instant defaults
                profile = Profile.objects.create(
                    user=user,
                    name=name,
                    character_class=random.choice(character_classes),
                    strength=default_stats['strength'],
                    intelligence=default_stats['intelligence'],
                    charisma=default_stats['charisma'],
                    endurance=default_stats['endurance'],
                    luck=default_stats['luck'],
                    goal=goal,  # Save the user's goal
                )
                
                # Create simple welcome message
                AIResponse.objects.create(
                    profile=profile,
                    role='assistant',
                    content=f'Welcome to Aura Growth, {name}! Your character is being customized by our AI - check back in a moment for your personalized profile and quests!'
                )
                
                # Generate basic starter quests instantly using fallbacks
                from .utils import generate_fallback_quests
                generate_fallback_quests(profile, create_objects=True)
                
                # Log in the user immediately
                login(request, user)
                messages.success(request, f'Character created! Welcome, {profile.character_class}!')
                
                # Schedule AI enhancement in background (after response is sent)
                try:
                    from .tasks import enhance_character_with_ai, generate_ai_quests
                    # Schedule AI enhancement for 5 seconds later (after user sees dashboard)
                    enhance_character_with_ai.apply_async(
                        args=[profile.id, name, role, interests, goal],
                        countdown=5
                    )
                    # Schedule quest generation for 10 seconds later  
                    generate_ai_quests.apply_async(
                        args=[profile.id],
                        countdown=10
                    )
                except ImportError:
                    print("Celery not available - background tasks skipped")
                except Exception as e:
                    # If Celery/Redis isn't available, log but don't fail registration
                    print(f"Background task scheduling failed: {e}")
                    # Registration still succeeds without background enhancement
                
                return redirect('dashboard')
                
        except Exception as e:
            messages.error(request, f'Error creating character: {str(e)}')
            return render(request, 'register.html')
    
    return render(request, 'register.html')


@login_required
def dashboard(request):
    """Main RPG dashboard with stats, quests, and status"""
    profile = get_object_or_404(Profile, user=request.user)
    
    # Get active quests
    daily_quests = profile.quests.filter(
        quest_type='daily',
        completed=False,
        due_date__gte=timezone.now().date()
    )[:5]
    
    # Get active habits
    active_habits = profile.habits.filter(active=True)[:3]
    
    # Get active status effects
    active_effects = profile.status_effects.filter(
        active=True,
        expires_at__gt=timezone.now()
    )
    
    # Calculate XP progress
    xp_progress = (profile.total_xp / profile.xp_to_next_level) * 100
    
    context = {
        'profile': profile,
        'daily_quests': daily_quests,
        'active_habits': active_habits,
        'active_effects': active_effects,
        'xp_progress': xp_progress,
    }
    
    return render(request, 'dashboard.html', context)


@login_required
def quests(request):
    """Quest log page showing all quests"""
    profile = get_object_or_404(Profile, user=request.user)
    
    # Get quests by type
    daily_quests = profile.quests.filter(quest_type='daily').order_by('-created_at')
    habit_quests = profile.quests.filter(quest_type='habit').order_by('-created_at')
    challenge_quests = profile.quests.filter(quest_type='challenge').order_by('-created_at')
    bonus_quests = profile.quests.filter(quest_type='bonus').order_by('-created_at')
    
    context = {
        'profile': profile,
        'daily_quests': daily_quests,
        'habit_quests': habit_quests,
        'challenge_quests': challenge_quests,
        'bonus_quests': bonus_quests,
    }
    
    return render(request, 'quests.html', context)


@login_required
def stats(request):
    """Stats and progress page"""
    profile = get_object_or_404(Profile, user=request.user)
    
    # Get recent log entries for progress tracking
    recent_logs = profile.log_entries.all()[:20]
    
    # Calculate completion rates
    total_quests = profile.quests.count()
    completed_quests = profile.quests.filter(completed=True).count()
    completion_rate = (completed_quests / total_quests * 100) if total_quests > 0 else 0
    
    context = {
        'profile': profile,
        'recent_logs': recent_logs,
        'completion_rate': completion_rate,
        'total_quests': total_quests,
        'completed_quests': completed_quests,
    }
    
    return render(request, 'stats.html', context)


@login_required
def chat(request):
    """AI chat interface with persistent history"""
    profile = get_object_or_404(Profile, user=request.user)
    
    # Get recent chat history (last 20 messages)
    chat_history = AIResponse.objects.filter(profile=profile).order_by('-timestamp')[:20]
    chat_history = list(reversed(chat_history))  # Reverse to show oldest first
    
    if request.method == 'POST':
        user_message = request.POST.get('message', '').strip()
        if not user_message:
            return JsonResponse({'error': 'Empty message'}, status=400)
        
        try:
            # Save user message to history
            AIResponse.objects.create(
                profile=profile,
                role='user',
                content=user_message
            )
            
            # Build context with recent history for better AI responses
            recent_messages = AIResponse.objects.filter(profile=profile).order_by('-timestamp')[:6]
            context_messages = []
            for msg in reversed(recent_messages):
                context_messages.append(f"{msg.role}: {msg.content}")
            
            # Enhanced AI prompt with goal awareness and personality
            personality_prompt = get_enhanced_personality_prompt(profile.ai_personality)
            goal_context = f"User's main goal: {profile.goal}" if profile.goal else "User hasn't set a specific goal yet."
            
            ai_prompt = f"""
            {personality_prompt}
            
            You are mentoring {profile.name}, a Level {profile.level} {profile.character_class}.
            Current stats: STR:{profile.strength} INT:{profile.intelligence} CHR:{profile.charisma} END:{profile.endurance} LCK:{profile.luck}
            {goal_context}
            Goal progress: {profile.goal_progress}%
            
            Recent conversation:
            {chr(10).join(context_messages[-4:]) if context_messages else "This is the start of our conversation."}
            
            Latest message: "{user_message}"
            
            Guidelines:
            - Stay in character with lots of personality and charisma
            - Reference their goal and suggest actions that help achieve it
            - Parse for quest completions, habit requests, or progress updates
            - If they mention progress toward their goal, suggest updating the progress bar
            - Be encouraging but realistic, with anime/RPG flair
            - Keep responses conversational and engaging
            
            Respond naturally without JSON code blocks.
            """
            
            raw_ai_response = generate_ai_response(ai_prompt, max_tokens=600)
            
            # Parse actions BEFORE cleaning the response
            action_data = parse_ai_action(raw_ai_response, profile)
            
            # Check for goal progress updates
            if profile.goal and any(word in user_message.lower() for word in ['progress', 'closer', 'achieved', 'completed', 'finished']):
                # Simple progress calculation - could be enhanced with AI
                progress_keywords = ['made progress', 'getting closer', 'almost there', 'halfway', 'completed']
                for i, keyword in enumerate(progress_keywords):
                    if keyword in user_message.lower():
                        new_progress = min(profile.goal_progress + (i + 1) * 10, 100)
                        if new_progress > profile.goal_progress:
                            profile.goal_progress = new_progress
                            profile.save()
                            action_data['goal_progress'] = new_progress
                        break
            
            # Clean the AI response
            clean_response = clean_ai_response(raw_ai_response)
            
            # Save AI response to history
            AIResponse.objects.create(
                profile=profile,
                role='assistant',
                content=clean_response
            )
            
            return JsonResponse({
                'response': clean_response,
                'action_data': action_data
            })
            
        except Exception as e:
            print(f"Chat error: {e}")
            return JsonResponse({'error': 'Failed to generate response'}, status=500)
    
    return render(request, 'chat.html', {
        'profile': profile,
        'chat_history': chat_history
    })


@login_required
def settings(request):
    """User settings and customization"""
    profile = get_object_or_404(Profile, user=request.user)
    
    if request.method == 'POST':
        # Update profile settings
        profile.name = request.POST.get('name', profile.name)
        profile.avatar = request.POST.get('avatar', profile.avatar)
        profile.ai_personality = request.POST.get('ai_personality', profile.ai_personality)
        profile.timezone = request.POST.get('timezone', profile.timezone)
        profile.save()
        
        messages.success(request, 'Settings updated successfully!')
        return redirect('settings')
    
    context = {
        'profile': profile,
    }
    
    return render(request, 'settings.html', context)


# HTMX API endpoints
@login_required
@require_http_methods(["POST"])
def complete_quest(request, quest_id):
    """HTMX endpoint to complete a quest"""
    try:
        profile = get_object_or_404(Profile, user=request.user)
        quest = get_object_or_404(Quest, id=quest_id, profile=profile)
        
        # Check if quest is already completed
        if quest.completed:
            return JsonResponse({
                'success': False, 
                'message': 'Quest already completed',
                'already_completed': True
            })
        
        # Check if quest is still valid (for daily quests)
        if quest.quest_type == 'daily' and quest.due_date and quest.due_date.date() < timezone.now().date():
            return JsonResponse({
                'success': False,
                'message': 'Quest has expired',
                'expired': True
            })
        
        # Complete the quest
        if quest.complete_quest():
            # Create log entry
            LogEntry.objects.create(
                profile=profile,
                action_type='quest_completed',
                action_description=f'Completed quest: {quest.title}',
                xp_gained=quest.reward_xp
            )
            
            # Refresh profile to get updated level
            profile.refresh_from_db()
            
            return JsonResponse({
                'success': True,
                'xp_gained': quest.reward_xp,
                'stat_gains': {
                    'strength': quest.reward_strength or 0,
                    'intelligence': quest.reward_intelligence or 0,
                    'charisma': quest.reward_charisma or 0,
                    'endurance': quest.reward_endurance or 0,
                    'luck': quest.reward_luck or 0,
                },
                'new_level': profile.level,
                'message': f'Quest completed! +{quest.reward_xp} XP',
                'quest_title': quest.title
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Failed to complete quest. Please try again.'
            })
            
    except Quest.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Quest not found'
        }, status=404)
    except Exception as e:
        import traceback
        print(f"Quest completion error: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'message': f'An error occurred while completing the quest: {str(e)}'
        }, status=500)


@login_required
def refresh_stats(request):
    """HTMX endpoint to refresh stats display"""
    profile = get_object_or_404(Profile, user=request.user)
    
    xp_progress = (profile.total_xp / profile.xp_to_next_level) * 100
    
    return JsonResponse({
        'level': profile.level,
        'total_xp': profile.total_xp,
        'xp_to_next_level': profile.xp_to_next_level,
        'xp_progress': xp_progress,
        'strength': profile.strength,
        'intelligence': profile.intelligence,
        'charisma': profile.charisma,
        'endurance': profile.endurance,
        'luck': profile.luck,
    })


@login_required
@require_http_methods(["POST"])
def generate_new_quests(request):
    """Generate new daily quests"""
    profile = get_object_or_404(Profile, user=request.user)
    
    try:
        new_quests = generate_daily_quests(profile)
        return JsonResponse({
            'success': True,
            'message': f'Generated {len(new_quests)} new quests!',
            'quest_count': len(new_quests)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error generating quests: {str(e)}'
        })
