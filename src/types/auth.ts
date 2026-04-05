export interface AuthUser {
  user_id: string;
  username: string;
}

export interface AuthSuccessResponse {
  access_token: string;
  token_type: 'bearer';
  user: AuthUser;
}
