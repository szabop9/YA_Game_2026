import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Observable, finalize } from 'rxjs';

type Phase = 'setup' | 'assignment' | 'categories' | 'quiz' | 'results';

interface Category {
  id: string;
  name: string;
  short_name: string;
  icon: string;
  color: string;
  double_points?: boolean;
}

interface Team {
  id: number;
  name: string;
  score: number;
  rank: number;
  category_id: string | null;
  category: Category | null;
  members: number[];
}

interface Question {
  id: string;
  prompt: string;
  answer: 'REAL' | 'AI';
  explanation: string;
  image?: string;
  kicker?: string;
  category_id: string;
  category: Category;
  round: number;
  number: number;
  total: number;
}

interface GameState {
  phase: Phase;
  player_count: number;
  current_question_index: number;
  revealed: boolean;
  categories: Category[];
  teams: Team[];
  current_question: Question | null;
}

@Component({
  selector: 'app-root',
  imports: [CommonModule, FormsModule],
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App implements OnInit {
  private readonly http = inject(HttpClient);
  readonly state = signal<GameState | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  playerCount = 30;

  ngOnInit(): void {
    this.loadState();
  }

  loadState(): void {
    this.request(this.http.get<GameState>('/api/state'));
  }

  createGame(): void {
    if (this.playerCount < 6 || this.playerCount > 100) {
      this.error.set('Please enter between 6 and 100 players.');
      return;
    }
    this.request(this.http.post<GameState>('/api/games', { player_count: this.playerCount }));
  }

  decrementPlayers(): void {
    this.playerCount = Math.max(6, this.playerCount - 1);
  }

  incrementPlayers(): void {
    this.playerCount = Math.min(100, this.playerCount + 1);
  }

  continueToCategories(): void {
    this.request(this.http.post<GameState>('/api/assignment/continue', {}));
  }

  chooseCategory(teamId: number, categoryId: string): void {
    this.request(this.http.put<GameState>(`/api/teams/${teamId}/category`, { category_id: categoryId }));
  }

  startQuiz(): void {
    this.request(this.http.post<GameState>('/api/quiz/start', {}));
  }

  adjustScore(teamId: number, delta: number): void {
    this.request(this.http.post<GameState>(`/api/teams/${teamId}/score`, { delta }));
  }

  reveal(): void {
    this.request(this.http.post<GameState>('/api/quiz/reveal', {}));
  }

  nextQuestion(): void {
    this.request(this.http.post<GameState>('/api/quiz/next', {}));
  }

  resetGame(): void {
    if (!confirm('Start a new game? All teams, choices and scores will be deleted.')) return;
    this.request(this.http.post<GameState>('/api/games/reset', {}));
  }

  allCategoriesChosen(): boolean {
    const game = this.state();
    return !!game?.teams.length && game.teams.every((team) => !!team.category_id);
  }

  chosenTeamsCount(): number {
    return this.state()?.teams.filter((team) => !!team.category_id).length ?? 0;
  }

  teamsByNumber(): Team[] {
    return [...(this.state()?.teams ?? [])].sort((first, second) => first.id - second.id);
  }

  awardValue(team: Team): number {
    const question = this.state()?.current_question;
    if (!question) return 1;
    const base = question.category.double_points ? 2 : 1;
    return team.category_id === question.category_id ? base * 2 : base;
  }

  isNextCategory(category: Category): boolean {
    const game = this.state();
    if (!game?.current_question) return false;
    const current = game.categories.findIndex((item) => item.id === game.current_question?.category_id);
    return game.categories[(current + 1) % game.categories.length].id === category.id;
  }

  podiumClass(rank: number): string {
    return rank === 1 ? 'gold' : rank === 2 ? 'silver' : rank === 3 ? 'bronze' : '';
  }

  trackTeam(_: number, team: Team): number {
    return team.id;
  }

  private request(observable: Observable<GameState>): void {
    this.busy.set(true);
    this.error.set('');
    observable.pipe(finalize(() => this.busy.set(false))).subscribe({
      next: (game) => this.state.set(game),
      error: (response) => this.error.set(response?.error?.detail || 'Something went wrong. Please try again.'),
    });
  }
}
