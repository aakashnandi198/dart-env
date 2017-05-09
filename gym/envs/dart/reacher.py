# This environment is created by Karen Liu (karen.liu@gmail.com)

import numpy as np
from gym import utils
from gym.envs.dart import dart_env

class DartReacherEnv(dart_env.DartEnv, utils.EzPickle):
    def __init__(self):
        self.target = np.array([0.8, -0.6, 0.6])
        self.action_scale = np.array([10, 10, 10, 10, 10])
        self.control_bounds = np.array([[1.0, 1.0, 1.0, 1.0, 1.0],[-1.0, -1.0, -1.0, -1.0, -1.0]])
        dart_env.DartEnv.__init__(self, 'reacher.skel', 4, 21, self.control_bounds)
        utils.EzPickle.__init__(self)

    def _step(self, a):
        clamped_control = np.array(a)
        for i in range(len(clamped_control)):
            if clamped_control[i] > self.control_bounds[0][i]:
                clamped_control[i] = self.control_bounds[0][i]
            if clamped_control[i] < self.control_bounds[1][i]:
                clamped_control[i] = self.control_bounds[1][i]
        tau = np.multiply(clamped_control, self.action_scale)

        #ALEX TEST NEW:
        fingertip = np.array([0.0, -0.25, 0.0])
        wFingertip1 = self.robot_skeleton.bodynodes[2].to_world(fingertip)
        vec1 = self.target-wFingertip1
        
        #apply action and simulate
        self.do_simulation(tau, self.frame_skip)
        
        wFingertip2 = self.robot_skeleton.bodynodes[2].to_world(fingertip)
        vec2 = self.target-wFingertip2
        
        reward_dist = - np.linalg.norm(vec2)
        reward_ctrl = - np.square(tau).sum() * 0.001
        reward_progress = np.dot((wFingertip2 - wFingertip1), vec1/np.linalg.norm(vec1)) * 100
        alive_bonus = -0.001
        reward = reward_progress + reward_ctrl + alive_bonus
        #END ALEX TEST NEW
        
        #old reward/simulation step
        '''
        fingertip = np.array([0.0, -0.25, 0.0])
        vec = self.robot_skeleton.bodynodes[2].to_world(fingertip) - self.target
        reward_dist = - np.linalg.norm(vec)
        reward_ctrl = - np.square(tau).sum() * 0.001
        alive_bonus = 0
        reward = reward_dist + reward_ctrl + alive_bonus
        
        self.do_simulation(tau, self.frame_skip)
        '''
        
        ob = self._get_obs()

        s = self.state_vector()
        velocity = np.square(s[5:]).sum()

        done = not (np.isfinite(s).all() and (-reward_dist > 0.1))
#        done = not (np.isfinite(s).all() and (-reward_dist > 0.01) and (velocity < 10000))

        aux_pred_signal = np.hstack([self.robot_skeleton.bodynodes[2].to_world(fingertip), [reward]])

        return ob, reward, done, {'aux_pred':aux_pred_signal, 'done_return':done}

    def _get_obs(self):
        theta = self.robot_skeleton.q
        fingertip = np.array([0.0, -0.25, 0.0])
        vec = self.robot_skeleton.bodynodes[2].to_world(fingertip) - self.target
        return np.concatenate([np.cos(theta), np.sin(theta), self.target, self.robot_skeleton.dq, vec]).ravel()
        #return np.concatenate([theta, self.robot_skeleton.dq, vec]).ravel()

    def reset_model(self):
        self.dart_world.reset()
        qpos = self.robot_skeleton.q + self.np_random.uniform(low=-.01, high=.01, size=self.robot_skeleton.ndofs)
        qvel = self.robot_skeleton.dq + self.np_random.uniform(low=-.01, high=.01, size=self.robot_skeleton.ndofs)
        self.set_state(qpos, qvel)
        while True:
            self.target = self.np_random.uniform(low=-1, high=1, size=3)
            #print('target = ' + str(self.target))
            if np.linalg.norm(self.target) < 1.5: break


        self.dart_world.skeletons[0].q=[0, 0, 0, self.target[0], self.target[1], self.target[2]]

        return self._get_obs()


    def viewer_setup(self):
        self._get_viewer().scene.tb.trans[2] = -3.5
        self._get_viewer().scene.tb._set_theta(0)
        self.track_skeleton_id = 0
