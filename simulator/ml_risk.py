"""Small educational ML risk classifier trained on deterministic synthetic vital-sign examples.
This is a software demonstration only; it is NOT trained/validated on clinical data and must
not be used for diagnosis or real patient care.
"""
import math, random

FEATURES = ("hr", "spo2", "rr", "sbp", "temp", "news2")
MEAN = (80.0, 96.0, 18.0, 120.0, 37.0, 2.0)
SCALE = (35.0, 8.0, 12.0, 35.0, 2.5, 5.0)

class SyntheticRiskClassifier:
    """Logistic-regression classifier trained on generated teaching examples."""
    def __init__(self):
        rng = random.Random(20261020)
        X, y = [], []
        # Generate stable, warning and high-risk examples with overlapping noise.
        for _ in range(5000):
            risk = rng.random()
            if risk < .55:
                hr=rng.gauss(78,12); spo2=rng.gauss(97,1.8); rr=rng.gauss(16,3); sbp=rng.gauss(122,16); temp=rng.gauss(36.9,.45)
            elif risk < .82:
                hr=rng.gauss(105,18); spo2=rng.gauss(92,3); rr=rng.gauss(23,5); sbp=rng.gauss(105,20); temp=rng.gauss(38,.8)
            else:
                hr=rng.gauss(137,24); spo2=rng.gauss(84,5); rr=rng.gauss(31,7); sbp=rng.gauss(83,18); temp=rng.gauss(39,.9)
            hr=max(25,min(240,hr));spo2=max(50,min(100,spo2));rr=max(1,min(65,rr));sbp=max(40,min(240,sbp));temp=max(30,min(43,temp))
            score = self._score(hr,spo2,rr,sbp,temp)
            features=self._features(hr,spo2,rr,sbp,temp,score)
            label=int(score>=5 or spo2<90 or hr>130 or hr<40 or rr>28 or sbp<85 or temp>=39.5)
            X.append(features);y.append(label)
        self.w=[0.0]*(len(FEATURES)+1)
        # Batch gradient descent for logistic regression
        for epoch in range(650):
            grad=[0.0]*len(self.w)
            for x,label in zip(X,y):
                z=self.w[0]+sum(a*b for a,b in zip(self.w[1:],x))
                z=max(-30,min(30,z));p=1/(1+math.exp(-z));err=p-label
                grad[0]+=err
                for j,val in enumerate(x,1):grad[j]+=err*val
            rate=.12/len(X)
            for j in range(len(self.w)):
                self.w[j]-=rate*(grad[j]+(0.0005*self.w[j] if j else 0))
        self.training_examples=len(X)
    @staticmethod
    def _score(hr,spo2,rr,sbp,temp):
        score=0
        score += 3 if hr<=40 or hr>=131 else 2 if hr<=50 or hr>=111 else 1 if hr>=91 else 0
        score += 3 if spo2<=91 else 2 if spo2<=92 else 1 if spo2<=95 else 0
        score += 3 if rr<=8 or rr>=25 else 2 if rr>=21 else 1 if rr==9 else 0
        score += 3 if sbp<=90 else 2 if sbp<=100 else 1 if sbp>=220 else 0
        score += 2 if temp<=35 else 2 if temp>=39 else 1 if temp>=38 else 0
        return score
    @staticmethod
    def _features(hr,spo2,rr,sbp,temp,score):
        raw=(hr,spo2,rr,sbp,temp,score)
        return [(v-m)/s for v,m,s in zip(raw,MEAN,SCALE)]
    def predict(self,vitals,news2_score=0):
        try:
            vals=[float(vitals.get(k,default)) for k,default in (("hr",78),("spo2",98),("rr",15),("sbp",120),("temp",36.8))]
            x=self._features(*vals,float(news2_score));z=self.w[0]+sum(a*b for a,b in zip(self.w[1:],x));p=1/(1+math.exp(-max(-30,min(30,z))))
            label="HIGH RISK" if p>=.7 else "ELEVATED" if p>=.4 else "LOW RISK"
            return {"probability":round(p,4),"label":label,"model":"synthetic-logistic-regression","training_examples":self.training_examples}
        except Exception:
            return {"probability":None,"label":"UNAVAILABLE","model":"synthetic-logistic-regression","training_examples":self.training_examples}
